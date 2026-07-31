import json
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from .espn import fetch_espn_plus_schedule
from .matcher import match_events
from .playlist import (
    filter_entries_by_day,
    filter_espn_plus,
    remove_no_event,
    streams_from_dispatcharr,
)
from .state import State, compute_playlist_hash

logger = logging.getLogger("espnplus")

DEFAULT_SETTINGS = {
    "epg_source_name": "ESPN+ EPG",
    "channel_id_prefix": "ESPN+",
    "channel_number_start": 900,
    "epg_group_name": "ESPN+",
    "epg_profile_name": "EPG",
    "look_ahead_days": 1,
    "min_similarity": 0.85,
    "keyword": "ESPN+",
    "espn_date": "today",
    "log_level": "INFO",
    "auto_refresh": True,
}


def merged_settings(settings: dict) -> dict:
    merged = dict(DEFAULT_SETTINGS)
    if isinstance(settings, dict):
        for key, value in settings.items():
            if value is not None:
                merged[key] = value
    return merged


def get_espn_days(settings: dict) -> list[str]:
    date_value = str(settings.get("espn_date", "today") or "today").strip()
    raw_look_ahead = settings.get("look_ahead_days", 1)
    if raw_look_ahead is None:
        raw_look_ahead = 1
    try:
        look_ahead = max(0, int(float(raw_look_ahead)))
    except (TypeError, ValueError):
        look_ahead = 1

    if date_value.lower() == "today":
        eastern = ZoneInfo("US/Eastern")
        now_et = datetime.now(eastern)
        days = []
        for i in range(look_ahead + 1):
            days.append((now_et + timedelta(days=i)).strftime("%Y-%m-%d"))
        return days
    return [date_value]


def validate_settings(settings: dict) -> dict:
    settings = merged_settings(settings)
    errors = []
    info = []

    for key in (
        "epg_source_name",
        "channel_id_prefix",
        "epg_group_name",
        "epg_profile_name",
        "keyword",
    ):
        if not str(settings.get(key, "")).strip():
            errors.append(f"'{key}' must not be empty")

    for key in ("channel_number_start", "min_similarity", "look_ahead_days"):
        try:
            float(settings.get(key, 0))
        except (TypeError, ValueError):
            errors.append(f"'{key}' must be a number")

    try:
        from apps.channels.models import Stream

        stream_count = Stream.objects.count()
        info.append(f"Dispatcharr database reachable ({stream_count} streams)")
    except Exception as e:
        errors.append(f"Could not query Dispatcharr database: {e}")

    try:
        from apps.epg.tasks import refresh_epg_data  # noqa: F401

        info.append("EPG task runner available")
    except Exception as e:
        errors.append(f"Could not import EPG tasks: {e}")

    return {
        "status": "ok" if not errors else "error",
        "errors": errors,
        "info": info,
    }


def run_once(settings: dict, dry_run: bool = False, force: bool = False) -> dict:
    settings = merged_settings(settings)
    logging.getLogger("espnplus").setLevel(
        getattr(logging, str(settings.get("log_level", "INFO")).upper(), logging.INFO)
    )

    state = State()

    from .sync import list_streams

    streams = list_streams()

    all_entries = streams_from_dispatcharr(streams)
    espn_entries = filter_espn_plus(all_entries, settings.get("keyword", "ESPN+"))
    espn_entries = remove_no_event(espn_entries)
    days = get_espn_days(settings)
    espn_entries = filter_entries_by_day(espn_entries, days)
    logger.info(
        f"Found {len(espn_entries)} {settings.get('keyword', 'ESPN+')} streams with events"
    )

    espn_events = []
    for day_iso in days:
        espn_events.extend(fetch_espn_plus_schedule(day_iso))

    matches = match_events(
        espn_entries,
        espn_events,
        min_similarity=float(settings.get("min_similarity", 0.85)),
    )
    matched_count = len(matches)
    logger.info(f"Matched {matched_count} events")

    fingerprint = sorted(
        (
            (entry.name or ""),
            (metadata or {}).get("start_time", ""),
            (metadata or {}).get("end_time", ""),
        )
        for entry, metadata in matches
    )
    run_hash = compute_playlist_hash(
        json.dumps(
            {"streams": streams, "matches": fingerprint},
            sort_keys=True,
            default=str,
        )
    )

    summary = {
        "status": "ok",
        "dry_run": dry_run,
        "streams": len(all_entries),
        "espn_streams": len(espn_entries),
        "days": days,
        "matches": matched_count,
    }

    if dry_run:
        for entry, metadata in matches:
            start = metadata.get("start_time", "")[:19]
            end = metadata.get("end_time", "")[:19]
            sport = metadata.get("sport", "")
            league = metadata.get("league", "")
            logger.info(
                "MATCH: %s | %s -> %s | sport=%s league=%s",
                entry.name, start, end, sport, league,
            )
        summary["message"] = f"Dry run: {matched_count} matches (no changes made)"
        state.save_status(summary)
        return summary

    cached_hash = state.load_hash()
    if not force and cached_hash == run_hash:
        logger.info("Nothing changed since last run — skipping")
        result = {
            "status": "skipped",
            "message": "No changes since last run — nothing to do",
        }
        state.save_status(result)
        return result

    state.save_hash(run_hash)

    if not matches:
        logger.warning("No matches found — skipping XMLTV and Dispatcharr update")
        summary["status"] = "ok"
        summary["message"] = "No matches found"
        state.save_status(summary)
        return summary

    from .sync import sync_to_dispatcharr

    try:
        sync_result = sync_to_dispatcharr(matches, settings)
    except Exception as e:
        logger.exception("Dispatcharr sync failed")
        raise

    summary.update(sync_result)
    state.save_status(summary)
    return summary
