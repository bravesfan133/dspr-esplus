import re
import logging
from datetime import datetime
from typing import Optional

from rapidfuzz import fuzz

from .normalize import normalize_title
from .playlist import PlaylistEntry

logger = logging.getLogger(__name__)

CORE_TITLE_PATTERN = re.compile(r"^ESPN\+\s*\d+:\s*(.*?)\s*@", re.IGNORECASE)


def extract_core_title(name: str) -> str:
    m = CORE_TITLE_PATTERN.match(name)
    if m:
        return m.group(1).strip()
    return name


def match_events(
    entries: list[PlaylistEntry],
    espn_events: list[dict],
    min_similarity: float = 0.85,
) -> list[tuple[PlaylistEntry, dict]]:
    matches = []

    for entry in entries:
        match = _match_single_entry(entry, espn_events, min_similarity)
        if match:
            matches.append((entry, match))
        else:
            logger.warning(f"Could not match playlist entry: {entry.name}")

    logger.info(f"Matched {len(matches)} events")
    return matches


def _match_single_entry(
    entry: PlaylistEntry,
    espn_events: list[dict],
    min_similarity: float,
) -> Optional[dict]:
    core = extract_core_title(entry.name)
    core_norm = normalize_title(core)

    if not core:
        return None

    target_ts = entry.start_time.timestamp() if entry.start_time else None

    best_event = None
    best_score = 0.0

    for event in espn_events:
        event_title = event.get("title") or ""
        event_short = event.get("short_name") or ""
        event_norm = normalize_title(event_title)

        for candidate_title in (event_title, event_short):
            if not candidate_title:
                continue

            if candidate_title.lower() == core.lower():
                return event

        if event_norm == core_norm:
            return event

        if core.lower() in event_title.lower() or event_title.lower() in core.lower():
            return event

        score = fuzz.token_sort_ratio(core_norm, event_norm) / 100.0
        if score > best_score:
            best_score = score
            best_event = event

    if best_score >= min_similarity and best_event:
        logger.debug(f"Matched '{entry.name}' -> '{best_event.get('title')}' (score: {best_score:.2f})")
        return best_event

    logger.debug(f"No match above threshold for '{entry.name}' (best: {best_score:.2f})")
    return None
