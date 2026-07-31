import logging
from datetime import datetime, timezone, timedelta
from typing import Optional
from xml.etree.ElementTree import Element, SubElement, tostring
from xml.dom import minidom
from zoneinfo import ZoneInfo

from src.playlist import PlaylistEntry

logger = logging.getLogger(__name__)

PACIFIC = ZoneInfo("America/Los_Angeles")
TITLE_PREFIX = "ESPN+:"
UPCOMING_PREFIX = "UPCOMING: "
ENDED_PREFIX = "ENDED: "
ENDED_HORIZON_HOURS = 3


def _escape_xml(text: Optional[str]) -> str:
    if not text:
        return ""
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;").replace("'", "&apos;")


def _format_xmltv_time(dt_str: Optional[str]) -> str:
    if not dt_str:
        return ""
    try:
        from dateutil import parser as dateparser
        dt = dateparser.parse(dt_str)
        dt = dt.astimezone(PACIFIC)
        return dt.strftime("%Y%m%d%H%M%S %z")
    except Exception:
        return dt_str


def _build_channel_id(entry: PlaylistEntry, prefix: str = "ESPN+") -> str:
    name_clean = "".join(c if c.isalnum() else "_" for c in entry.name)
    return f"{prefix}.{name_clean}"


def _emit_programme(
    parent,
    channel_id: str,
    title: str,
    start_dt,
    end_dt,
    metadata: Optional[dict] = None,
    image_url: str = "",
    is_live: bool = False,
    is_real: bool = False,
):
    prog = SubElement(parent, "programme")
    prog.set("channel", channel_id)
    prog.set("start", _format_xmltv_time(start_dt.isoformat()))
    prog.set("stop", _format_xmltv_time(end_dt.isoformat()))

    title_el = SubElement(prog, "title")
    title_el.set("lang", "en")
    title_el.text = _escape_xml(title)

    if image_url:
        icon_el = SubElement(prog, "icon")
        icon_el.set("src", _escape_xml(image_url))

    if is_real:
        desc_text = _build_description(metadata)
        if desc_text:
            desc_el = SubElement(prog, "desc")
            desc_el.set("lang", "en")
            desc_el.text = _escape_xml(desc_text)
    if metadata:
        cat_sports = SubElement(prog, "category")
        cat_sports.set("lang", "en")
        cat_sports.text = "Sports"
        if not metadata.get("is_studio"):
            cat_event = SubElement(prog, "category")
            cat_event.set("lang", "en")
            cat_event.text = "Sports Event"
        sport = metadata.get("sport", "")
        league = metadata.get("league", "")
        subcategory = metadata.get("subcategory", "")
        if sport:
            cat_el = SubElement(prog, "category")
            cat_el.set("lang", "en")
            cat_el.text = _escape_xml(sport)
        if league:
            cat_el2 = SubElement(prog, "category")
            cat_el2.set("lang", "en")
            cat_el2.text = _escape_xml(league)
        if subcategory and subcategory != league:
            cat_el3 = SubElement(prog, "category")
            cat_el3.set("lang", "en")
            cat_el3.text = _escape_xml(subcategory)

    if is_live:
        SubElement(prog, "live")
    if is_real:
        SubElement(prog, "new")
        SubElement(prog, "premiere")


def generate_xmltv(
    matches: list[tuple[PlaylistEntry, dict]],
    prefix: str = "ESPN+",
) -> str:
    root = Element("tv")
    root.set("generator-info-name", "Dispatcharr ESPN+ EPG Generator")

    for entry, metadata in matches:
        channel_id = _build_channel_id(entry, prefix)

        channel_el = SubElement(root, "channel")
        channel_el.set("id", channel_id)

        display_name = SubElement(channel_el, "display-name")
        display_name.text = _escape_xml(entry.name)

        if entry.tvg_logo:
            icon = SubElement(channel_el, "icon")
            icon.set("src", _escape_xml(entry.tvg_logo))

        real_start_str = metadata.get("start_time") or ""
        real_end_str = metadata.get("end_time") or ""
        if not real_start_str or not real_end_str:
            continue

        try:
            from dateutil import parser as dateparser
            real_start = dateparser.parse(real_start_str).astimezone(PACIFIC)
            real_end = dateparser.parse(real_end_str).astimezone(PACIFIC)
            if real_end <= real_start:
                continue
        except Exception:
            continue

        real_title = f"{TITLE_PREFIX} {(metadata.get('short_name') or metadata.get('title') or entry.name).strip()}"
        image_url = metadata.get("image_url") or ""
        is_studio = metadata.get("is_studio", False)

        day_before = real_start - timedelta(days=1)
        upcoming_start_pt = day_before.replace(hour=0, minute=0, second=0, microsecond=0)

        if upcoming_start_pt < real_start:
            _emit_programme(
                root, channel_id,
                title=UPCOMING_PREFIX + real_title,
                start_dt=upcoming_start_pt,
                end_dt=real_start,
                metadata=metadata,
                image_url=image_url,
                is_real=False,
            )

        _emit_programme(
            root, channel_id,
            title=real_title,
            start_dt=real_start,
            end_dt=real_end,
            metadata=metadata,
            image_url=image_url,
            is_live=not is_studio,
            is_real=True,
        )

        ended_end_pt = real_end + timedelta(hours=ENDED_HORIZON_HOURS)
        _emit_programme(
            root, channel_id,
            title=ENDED_PREFIX + real_title,
            start_dt=real_end,
            end_dt=ended_end_pt,
            metadata=metadata,
            image_url=image_url,
            is_real=False,
        )

    rough_string = tostring(root, encoding="unicode")
    reparsed = minidom.parseString(rough_string.encode("utf-8"))
    pretty = reparsed.toprettyxml(indent="  ", encoding="utf-8")
    return pretty.decode("utf-8") if isinstance(pretty, bytes) else pretty


def _build_description(metadata: dict) -> str:
    parts = []
    extra = []
    if metadata.get("league"):
        extra.append(metadata["league"])
    if metadata.get("subcategory") and metadata["subcategory"] != metadata.get("league"):
        extra.append(metadata["subcategory"])
    if metadata.get("sport"):
        extra.append(metadata["sport"])
    if extra:
        parts.append(" | ".join(extra))
    if metadata.get("is_studio"):
        parts.append("Studio show")
    return " — ".join(parts)


def get_channel_id(entry: PlaylistEntry, prefix: str = "ESPN+") -> str:
    return _build_channel_id(entry, prefix)
