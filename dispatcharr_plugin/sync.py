import logging
import os
import time
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

from .extract import extract_channel_number_index
from .playlist import event_ends_after, extract_espn_datetime
from .xmltv_gen import generate_xmltv, get_channel_id

logger = logging.getLogger(__name__)

EPG_UPLOAD_DIR = "/data/uploads/epgs"
EPG_FILENAME = "espnplus_epg.xml"
EPG_FILE = os.path.join(EPG_UPLOAD_DIR, EPG_FILENAME)

WAIT_TIMEOUT_SECONDS = 120.0
WAIT_POLL_SECONDS = 2.0


def target_channel_number(entry, channel_number_start: float) -> Optional[float]:
    n = extract_channel_number_index(entry.name)
    if n is None:
        return None
    return float(channel_number_start) + (n - 1)


def channel_sort_key(item) -> tuple:
    entry, _ = item
    n = extract_channel_number_index(entry.name)
    return (n is None, n if n is not None else 0)


def list_streams() -> list[dict]:
    from apps.channels.models import Stream

    return [
        {
            "id": s.id,
            "name": s.name,
            "url": s.url,
            "tvg_id": s.tvg_id,
            "logo_url": s.logo_url,
            "channel_group": s.channel_group_id,
        }
        for s in Stream.objects.all()
    ]


def wait_for_epg_refresh(
    source_id: int,
    timeout: float = WAIT_TIMEOUT_SECONDS,
    interval: float = WAIT_POLL_SECONDS,
) -> bool:
    from apps.epg.models import EPGSource

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            src = EPGSource.objects.filter(pk=source_id).only(
                "status", "last_message"
            ).first()
        except Exception:
            src = None
        if src is None:
            return False
        status = src.status or ""
        message = src.last_message or ""
        if status == EPGSource.STATUS_SUCCESS and "programs for" in message:
            logger.info(f"EPG refresh complete: {message}")
            return True
        if status in (EPGSource.STATUS_ERROR, EPGSource.STATUS_DISABLED):
            logger.warning(f"EPG refresh failed for source {source_id}: {message}")
            return False
        time.sleep(interval)
    logger.warning(f"Timed out waiting for EPG refresh of source {source_id}")
    return False


def _get_or_create_source(source_name: str):
    from apps.epg.models import EPGSource

    source, created = EPGSource.objects.get_or_create(
        name=source_name,
        defaults={
            "source_type": "xmltv",
            "file_path": EPG_FILE,
            "is_active": True,
            "refresh_interval": 1440,
            "priority": 1,
        },
    )
    if not created:
        update_fields = []
        if source.file_path != EPG_FILE:
            source.file_path = EPG_FILE
            update_fields.append("file_path")
        if source.source_type != "xmltv":
            source.source_type = "xmltv"
            update_fields.append("source_type")
        if source.is_active is False:
            source.is_active = True
            update_fields.append("is_active")
        if update_fields:
            source.save(update_fields=update_fields)
    return source


def upsert_epg_rows(source, sorted_matches: list, prefix: str) -> dict:
    from apps.epg.models import EPGData

    try:
        name_max_length = EPGData._meta.get_field("name").max_length
    except Exception:
        name_max_length = 512

    epg_rows = {}
    for entry, _metadata in sorted_matches:
        tvg_id = get_channel_id(entry, prefix=prefix)
        name = (entry.name or "")[:name_max_length] if name_max_length else entry.name or ""
        defaults = {"name": name}
        if entry.tvg_logo:
            defaults["icon_url"] = entry.tvg_logo
        row, _created = EPGData.objects.update_or_create(
            epg_source=source,
            tvg_id=tvg_id,
            defaults=defaults,
        )
        epg_rows[tvg_id] = row
    return epg_rows


def assign_channel_logos(xmltv_to_channel: dict, sorted_matches: list, prefix: str) -> int:
    """Link each channel to a Logo derived from the stream's tvg_logo.

    Mirrors Dispatcharr's 'set-logos-from-epg' task but synchronously from our
    own data, so the M3U/EPG output carries tvg-logo for Channels DVR.
    """
    from apps.channels.models import Logo

    assigned = 0
    for entry, _metadata in sorted_matches:
        logo_url = (entry.tvg_logo or "").strip()
        if not logo_url:
            continue
        channel = xmltv_to_channel.get(get_channel_id(entry, prefix=prefix))
        if channel is None:
            continue
        if channel.logo_id is not None:
            try:
                if channel.logo.url == logo_url:
                    continue
            except Exception:
                pass
        logo, _created = Logo.objects.get_or_create(
            url=logo_url,
            defaults={"name": (entry.tvg_name or entry.name or "")[:255]},
        )
        if channel.logo_id != logo.id:
            channel.logo_id = logo.id
            channel.save(update_fields=["logo_id"])
            assigned += 1
    if assigned:
        logger.info(f"Assigned logos to {assigned} channels")
    return assigned


def assign_epg_data(xmltv_to_channel: dict, epg_rows: dict) -> int:
    associated = 0
    for xmltv_id, channel in xmltv_to_channel.items():
        row = epg_rows.get(xmltv_id)
        if row is not None and channel.epg_data_id != row.id:
            channel.epg_data = row
            channel.save(update_fields=["epg_data"])
            associated += 1
    return associated


def trigger_refresh_and_wait(source_id: int) -> bool:
    from apps.epg.models import EPGSource
    from apps.epg.tasks import refresh_epg_data

    refresh_epg_data.delay(source_id, force=True)
    if wait_for_epg_refresh(source_id):
        return True

    try:
        src = EPGSource.objects.filter(pk=source_id).only("status").first()
    except Exception:
        src = None
    if src is not None and src.status in (
        EPGSource.STATUS_ERROR,
        EPGSource.STATUS_DISABLED,
    ):
        return False

    logger.info("EPG refresh timed out without error — retrying once")
    refresh_epg_data.delay(source_id, force=True)
    return wait_for_epg_refresh(source_id)


def remove_stale_channels(
    existing: dict,
    keep_names: set,
    group,
    prev_day_events: list[dict],
    boundary_dt: datetime,
    active_indices: Optional[set] = None,
) -> tuple[int, list[str]]:
    """Delete channels whose event date is before `boundary_dt`, unless the event
    goes between days (ends at/after the boundary). A previous-day channel whose
    ESPN+ index is reused by a current match is removed (replaced) regardless.
    Returns (removed, tvg_ids)."""
    active_indices = active_indices or set()
    removed = 0
    removed_tvg_ids = []
    for name_lower, channel in existing.items():
        if name_lower in keep_names:
            continue
        if channel.channel_group_id != group.id:
            continue
        start = extract_espn_datetime(channel.name)
        if start is None:
            continue
        if start.date() >= boundary_dt.date():
            continue
        index = extract_channel_number_index(channel.name)
        if index is not None and index in active_indices:
            logger.info(f"Removing replaced channel: {channel.name}")
        elif event_ends_after(prev_day_events, start, boundary_dt):
            logger.info(f"Keeping between-days channel: {channel.name}")
            continue
        else:
            logger.info(f"Removing stale channel from previous day: {channel.name}")
        channel.delete()
        removed += 1
        removed_tvg_ids.append(channel.tvg_id)
    if removed:
        logger.info(f"Removed {removed} stale channels from previous days")
    return removed, removed_tvg_ids


def sync_to_dispatcharr(
    matches: list,
    settings: dict,
    prev_day_events: Optional[list[dict]] = None,
    reference_date: Optional[str] = None,
) -> dict:
    from apps.channels.models import (
        Channel,
        ChannelGroup,
        ChannelProfile,
        ChannelProfileMembership,
        ChannelStream,
        Stream,
    )

    epg_profile_name = str(settings.get("epg_profile_name", "EPG")).strip() or "EPG"
    epg_group_name = str(settings.get("epg_group_name", "ESPN+")).strip() or "ESPN+"
    channel_id_prefix = str(settings.get("channel_id_prefix", "ESPN+")).strip() or "ESPN+"
    channel_number_start = float(settings.get("channel_number_start", 900) or 900)
    source_name = str(settings.get("epg_source_name", "ESPN+ EPG")).strip() or "ESPN+ EPG"

    profile, _ = ChannelProfile.objects.get_or_create(name=epg_profile_name)
    group, _ = ChannelGroup.objects.get_or_create(name=epg_group_name)

    existing = {c.name.lower(): c for c in Channel.objects.all()}
    stream_by_id = {s.id: s for s in Stream.objects.all()}
    sorted_matches = sorted(matches, key=channel_sort_key)

    created = 0
    updated = 0
    associated = 0
    xmltv_to_channel = {}
    profile_memberships = []

    for entry, _metadata in sorted_matches:
        xmltv_id = get_channel_id(entry, prefix=channel_id_prefix)
        target = target_channel_number(entry, channel_number_start)

        channel = existing.get((entry.name or "").lower())
        if channel is None:
            channel = Channel.objects.create(
                name=entry.name,
                tvg_id=xmltv_id,
                channel_group=group,
                channel_number=target,
            )
            created += 1
        else:
            update_fields = []
            if channel.tvg_id != xmltv_id:
                channel.tvg_id = xmltv_id
                update_fields.append("tvg_id")
            if channel.channel_group_id != group.id:
                channel.channel_group = group
                update_fields.append("channel_group")
            if target is not None and channel.channel_number is None:
                channel.channel_number = target
                update_fields.append("channel_number")
            if update_fields:
                channel.save(update_fields=update_fields)
            updated += 1

        stream = stream_by_id.get(entry.stream_id)
        if stream is not None:
            if not channel.streams.filter(id=stream.id).exists():
                ChannelStream.objects.create(channel=channel, stream=stream)

        xmltv_to_channel[xmltv_id] = channel
        profile_memberships.append((profile, channel))

    for profile, channel in profile_memberships:
        ChannelProfileMembership.objects.update_or_create(
            channel_profile=profile,
            channel=channel,
            defaults={"enabled": True},
        )

    logger.info(f"Created {created} new Dispatcharr channels")
    logger.info(f"Updated {updated} existing channels")

    eastern = ZoneInfo("US/Eastern")
    if reference_date:
        try:
            boundary_dt = datetime.strptime(reference_date, "%Y-%m-%d").replace(
                tzinfo=eastern
            )
        except (TypeError, ValueError):
            boundary_dt = datetime.now(eastern).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
    else:
        boundary_dt = datetime.now(eastern).replace(
            hour=0, minute=0, second=0, microsecond=0
        )

    keep_names = {(entry.name or "").lower() for entry, _ in sorted_matches}
    active_indices = {
        extract_channel_number_index(entry.name) for entry, _ in sorted_matches
    }
    active_indices.discard(None)
    removed, removed_tvg_ids = remove_stale_channels(
        existing,
        keep_names,
        group,
        prev_day_events or [],
        boundary_dt,
        active_indices=active_indices,
    )

    xml_content = generate_xmltv(sorted_matches, prefix=channel_id_prefix)
    os.makedirs(EPG_UPLOAD_DIR, exist_ok=True)
    with open(EPG_FILE, "w", encoding="utf-8") as f:
        f.write(xml_content)
    logger.info(f"Generated XMLTV and wrote {EPG_FILE}")

    source = _get_or_create_source(source_name)

    epg_rows = upsert_epg_rows(source, sorted_matches, channel_id_prefix)
    logger.info(f"Upserted {len(epg_rows)} EPG channel rows for source {source_name}")

    if removed_tvg_ids:
        from apps.epg.models import EPGData

        stale, _ = EPGData.objects.filter(
            epg_source=source, tvg_id__in=removed_tvg_ids
        ).delete()
        logger.info(f"Deleted {stale} stale EPG rows for removed channels")

    associated = assign_epg_data(xmltv_to_channel, epg_rows)
    logger.info(f"Assigned EPG data to {associated} channels")

    assigned_logos = assign_channel_logos(xmltv_to_channel, sorted_matches, channel_id_prefix)

    refreshed = trigger_refresh_and_wait(source.id)
    if not refreshed:
        logger.warning("EPG program refresh did not complete as expected")

    return {
        "created": created,
        "updated": updated,
        "removed": removed,
        "associated": associated,
        "assigned_logos": assigned_logos,
        "epg_source": source_name,
        "refreshed": refreshed,
        "message": (
            f"Synced {len(sorted_matches)} channels; "
            f"created {created}, updated {updated}, removed {removed}"
        ),
    }
