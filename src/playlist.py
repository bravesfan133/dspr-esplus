import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Optional

from dateutil import parser as dateparser

logger = logging.getLogger(__name__)

TITLE_PATTERN = re.compile(
    r"^ESPN\+\s+\d+:\s+(?!En Español)"
    r"(?P<display_title>(?:(?P<league>[^:]+):\s*)?"
    r"(?:(?P<team2>.+?)\s*(?:vs\.?|VS\.?)\s*(?P<team1>.+?)|.+?))\s*@",
    re.IGNORECASE,
)

TIME_PATTERN = re.compile(
    r"@.*?\b(?P<hour>\d{1,2}):(?P<minute>\d{2})\s*(?P<ampm>AM|PM)\b",
    re.IGNORECASE,
)

DATE_PATTERN = re.compile(
    r"@\s*(?P<month>[A-Za-z]{3})\s+(?P<day>\d{1,2})",
    re.IGNORECASE,
)


@dataclass
class PlaylistEntry:
    name: str
    stream_url: str
    tvg_id: Optional[str] = None
    tvg_name: Optional[str] = None
    tvg_logo: Optional[str] = None
    group: Optional[str] = None
    tvg_chno: Optional[str] = None
    stream_id: Optional[int] = None
    start_time: Optional[datetime] = None


def extract_espn_datetime(name: str) -> Optional[datetime]:
    if "ESPN+" not in name.upper():
        return None

    time_match = TIME_PATTERN.search(name)
    date_match = DATE_PATTERN.search(name)

    if not time_match or not date_match:
        return None

    hour = int(time_match.group("hour"))
    minute = int(time_match.group("minute"))
    ampm = time_match.group("ampm").upper()

    if ampm == "PM" and hour != 12:
        hour += 12
    elif ampm == "AM" and hour == 12:
        hour = 0

    month_str = date_match.group("month")
    day = int(date_match.group("day"))

    now = datetime.now(timezone.utc)
    year = now.year

    try:
        month = dateparser.parse(f"{month_str} 1").month
    except Exception:
        return None

    from zoneinfo import ZoneInfo
    eastern = ZoneInfo("US/Eastern")

    try:
        dt = datetime(year, month, day, hour, minute, tzinfo=eastern)
    except ValueError:
        return None

    return dt


def extract_display_title(name: str) -> Optional[str]:
    match = TITLE_PATTERN.match(name)
    if match:
        return match.group("display_title").strip()
    return None


def streams_from_dispatcharr(streams: list[dict]) -> list[PlaylistEntry]:
    entries = []
    for s in streams:
        name = s.get("name", "") or ""
        stream_url = s.get("url", "") or ""

        tvg_id = s.get("tvg_id")
        logo_url = s.get("logo_url")

        group_id = s.get("channel_group")

        entry = PlaylistEntry(
            name=name,
            stream_url=stream_url,
            tvg_id=tvg_id,
            tvg_name=name,
            tvg_logo=logo_url,
            group=str(group_id) if group_id is not None else None,
            stream_id=s.get("id"),
        )
        entry.start_time = extract_espn_datetime(name)
        entries.append(entry)

    logger.debug(f"Converted {len(entries)} Dispatcharr streams to PlaylistEntries")
    return entries


def parse_m3u(content: str) -> list[PlaylistEntry]:
    entries = []
    lines = content.strip().split("\n")
    i = 0

    while i < len(lines):
        line = lines[i].strip()

        if line.startswith("#EXTINF:"):
            info_line = line
            i += 1

            stream_url = ""
            while i < len(lines) and (lines[i].strip() == "" or lines[i].startswith("#")):
                i += 1

            if i < len(lines):
                stream_url = lines[i].strip()

            entry = _parse_extinf(info_line, stream_url)
            if entry:
                entries.append(entry)
        elif line.startswith("#EXTM3U"):
            pass

        i += 1

    logger.debug(f"Parsed {len(entries)} entries from playlist")
    return entries


def _parse_extinf(extinf_line: str, stream_url: str) -> Optional[PlaylistEntry]:
    match = re.search(r'#EXTINF:(?:-?\d+(?:\.\d+)?)', extinf_line)
    if not match:
        return None

    tvg_id = _extract_attr(extinf_line, "tvg-id")
    tvg_name = _extract_attr(extinf_line, "tvg-name")
    tvg_logo = _extract_attr(extinf_line, "tvg-logo")
    tvg_chno = _extract_attr(extinf_line, "tvg-chno")

    group = _extract_attr(extinf_line, "group-title")

    name = _extract_name(extinf_line)

    entry = PlaylistEntry(
        name=name,
        stream_url=stream_url,
        tvg_id=tvg_id,
        tvg_name=tvg_name,
        tvg_logo=tvg_logo,
        group=group,
        tvg_chno=tvg_chno,
    )
    entry.start_time = extract_espn_datetime(name)
    return entry


def _extract_attr(line: str, attr: str) -> Optional[str]:
    pattern = re.compile(rf'{re.escape(attr)}\s*=\s*"([^"]*)"', re.IGNORECASE)
    match = pattern.search(line)
    if match:
        value = match.group(1).strip()
        return value if value else None
    return None


def _extract_name(line: str) -> str:
    parts = line.rsplit(",", 1)
    if len(parts) == 2:
        return parts[1].strip()
    return line.strip()


def filter_espn_plus(entries: list[PlaylistEntry], keyword: str = "ESPN+") -> list[PlaylistEntry]:
    result = [e for e in entries if keyword.upper() in e.name.upper()]
    logger.info(f"Found {len(result)} {keyword} streams out of {len(entries)} total")
    return result


def remove_no_event(entries: list[PlaylistEntry]) -> list[PlaylistEntry]:
    result = [e for e in entries if "NO EVENT" not in e.name.upper()]
    skipped = len(entries) - len(result)
    if skipped:
        logger.info(f"Skipped {skipped} streams with 'NO EVENT' in name")
    return result


def filter_entries_by_day(entries: list[PlaylistEntry], days: list[str]) -> list[PlaylistEntry]:
    result = []
    for e in entries:
        if e.start_time is None:
            logger.info(f"Filtered out stream without a parseable date: {e.name}")
            continue
        day_iso = e.start_time.strftime("%Y-%m-%d")
        if day_iso in days:
            result.append(e)
        else:
            logger.info(f"Filtered out off-day stream ({day_iso}): {e.name}")
    return result
