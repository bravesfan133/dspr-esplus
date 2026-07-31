import logging
import os
import time
from typing import Optional

from .extract import extract_channel_number_index
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
        row, _created = EPGData.objects.update_or_create(
            epg_source=source,
            tvg_id=tvg_id,
            defaults={"name": name},
        )
        epg_rows[tvg_id] = row
    return epg_rows


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


def sync_to_dispatcharr(matches: list, settings: dict) -> dict:
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

    xml_content = generate_xmltv(sorted_matches, prefix=channel_id_prefix)
    os.makedirs(EPG_UPLOAD_DIR, exist_ok=True)
    with open(EPG_FILE, "w", encoding="utf-8") as f:
        f.write(xml_content)
    logger.info(f"Generated XMLTV and wrote {EPG_FILE}")

    source = _get_or_create_source(source_name)

    epg_rows = upsert_epg_rows(source, sorted_matches, channel_id_prefix)
    logger.info(f"Upserted {len(epg_rows)} EPG channel rows for source {source_name}")

    associated = assign_epg_data(xmltv_to_channel, epg_rows)
    logger.info(f"Assigned EPG data to {associated} channels")

    refreshed = trigger_refresh_and_wait(source.id)
    if not refreshed:
        logger.warning("EPG program refresh did not complete as expected")

    return {
        "created": created,
        "updated": updated,
        "associated": associated,
        "epg_source": source_name,
        "refreshed": refreshed,
        "message": f"Synced {len(sorted_matches)} channels; created {created}, updated {updated}",
    }
