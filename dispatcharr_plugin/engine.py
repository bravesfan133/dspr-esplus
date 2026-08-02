import json
import logging
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from .channels_dvr import (
    derive_epg_lineup_name,
    list_sources,
    refresh_epg_lineup,
    refresh_m3u_source,
)
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
    "channels_dvr_enabled": False,
    "channels_dvr_base_url": "",
    "channels_dvr_m3u_source": "",
    "channels_dvr_epg_lineup": "",
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

    if bool(settings.get("channels_dvr_enabled", False)):
        if not str(settings.get("channels_dvr_base_url", "") or "").strip():
            errors.append(
                "'channels_dvr_base_url' must be set when Channels DVR refresh is enabled"
            )
        if not str(settings.get("channels_dvr_m3u_source", "") or "").strip():
            errors.append(
                "'channels_dvr_m3u_source' must be selected when Channels DVR refresh is enabled"
            )

    return {
        "status": "ok" if not errors else "error",
        "errors": errors,
        "info": info,
    }


def _channels_dvr_summary(settings: dict) -> dict:
    """Run the Channels DVR refresh and wrap any exception into a result dict."""
    try:
        return refresh_channels_dvr(settings)
    except Exception as e:
        logger.exception("Channels DVR refresh failed")
        return {"status": "error", "message": f"{type(e).__name__}: {e}"}


def refresh_channels_dvr(settings: dict) -> dict:
    """Refresh the selected M3U source and XMLTV lineup on Channels DVR."""
    if not bool(settings.get("channels_dvr_enabled", False)):
        return {"status": "skipped", "message": "Channels DVR refresh disabled in settings"}

    base_url = str(settings.get("channels_dvr_base_url", "") or "").strip()
    if not base_url:
        return {"status": "skipped", "message": "Channels DVR base URL not set"}

    source_name = str(settings.get("channels_dvr_m3u_source", "") or "").strip()
    if not source_name:
        return {"status": "skipped", "message": "No Channels DVR M3U source selected"}

    device_id = None
    try:
        sources_result = list_sources(base_url)
        for source in sources_result.get("m3u_sources", []):
            if source.get("name") == source_name:
                device_id = source.get("device_id")
                break
    except Exception as e:
        logger.warning(f"Could not look up Channels DVR source device id: {e}")

    m3u_ok = refresh_m3u_source(base_url, source_name, device_id=device_id)
    time.sleep(5)

    lineup_name = str(settings.get("channels_dvr_epg_lineup", "") or "").strip()
    if not lineup_name:
        lineup_name = derive_epg_lineup_name(source_name)
    epg_ok = refresh_epg_lineup(base_url, lineup_name)

    if m3u_ok and epg_ok:
        return {
            "status": "ok",
            "message": (
                f"Channels DVR refreshed: M3U '{source_name}', EPG '{lineup_name}'"
            ),
        }
    problems = []
    if not m3u_ok:
        problems.append(f"M3U refresh failed for '{source_name}'")
    if not epg_ok:
        problems.append(f"EPG refresh failed for '{lineup_name}'")
    return {"status": "error", "message": "; ".join(problems)}


def test_channels_dvr_refresh(settings: dict) -> dict:
    """Perform the real M3U POST and EPG PUT refresh and report each URL + status."""
    settings = merged_settings(settings)
    base_url = str(settings.get("channels_dvr_base_url", "") or "").strip()
    if not base_url:
        return {
            "status": "error",
            "message": "Set the 'Channels DVR Base URL' setting first, then save settings.",
        }
    source_name = str(settings.get("channels_dvr_m3u_source", "") or "").strip()
    if not source_name:
        return {
            "status": "error",
            "message": "Set the 'Channels DVR M3U Source' setting first, then save settings.",
        }
    lineup_name = str(settings.get("channels_dvr_epg_lineup", "") or "").strip()
    if not lineup_name:
        lineup_name = derive_epg_lineup_name(source_name)

    from .channels_dvr import refresh_and_report

    return refresh_and_report(base_url, source_name, lineup_name=lineup_name)


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

    prev_day_events = []
    try:
        first_day = datetime.strptime(days[0], "%Y-%m-%d").date()
        prev_day_iso = (first_day - timedelta(days=1)).strftime("%Y-%m-%d")
        prev_day_events = fetch_espn_plus_schedule(prev_day_iso)
    except (ValueError, TypeError, IndexError):
        prev_day_events = []

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
        if bool(settings.get("channels_dvr_enabled", False)):
            result["channels_dvr"] = _channels_dvr_summary(settings)
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
        sync_result = sync_to_dispatcharr(
            matches,
            settings,
            prev_day_events=prev_day_events,
            reference_date=days[0] if days else None,
        )
    except Exception as e:
        logger.exception("Dispatcharr sync failed")
        raise

    summary.update(sync_result)
    if bool(settings.get("channels_dvr_enabled", False)):
        summary["channels_dvr"] = _channels_dvr_summary(settings)
    state.save_status(summary)
    return summary
