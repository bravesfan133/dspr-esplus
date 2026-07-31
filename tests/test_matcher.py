from datetime import datetime, timezone

from src.matcher import match_events, extract_core_title
from src.playlist import PlaylistEntry


def make_entry(name: str, start_time: datetime = None) -> PlaylistEntry:
    if start_time is None:
        start_time = datetime.now(timezone.utc)
    entry = PlaylistEntry(
        name=name,
        stream_url="http://example.com/stream",
        start_time=start_time,
    )
    return entry


def make_event(title: str, start_ts: int = 0) -> dict:
    return {
        "title": title,
        "short_name": title,
        "start_timestamp": start_ts,
        "end_timestamp": start_ts + 7200,
        "start_time": datetime.fromtimestamp(start_ts, tz=timezone.utc).isoformat(),
        "end_time": datetime.fromtimestamp(start_ts + 7200, tz=timezone.utc).isoformat(),
        "sport": "Football",
        "league": "NFL",
        "is_studio": False,
    }


def test_exact_title_match():
    entry = make_entry("ESPN+ 27: Australia vs. USA Women's National Team @ Jul 30 8:00PM ET")
    event = make_event("Australia vs. USA Women's National Team")
    matches = match_events([entry], [event])
    assert len(matches) == 1
    assert matches[0][1]["title"] == event["title"]


def test_substring_match():
    entry = make_entry("ESPN+ 11: Panathinaikos vs. Paksi FC @ Jul 30 12:05PM ET")
    event = make_event("Panathinaikos vs. Paksi FC (UEFA Europa League)")
    matches = match_events([entry], [event])
    assert len(matches) == 1


def test_case_insensitive_match():
    entry = make_entry("ESPN+ 19: Rocket Classic: Spieth Featured Group (First Round) @ Jul 30 3:00PM ET")
    event = make_event("Rocket Classic: Spieth Featured Group (First Round)")
    matches = match_events([entry], [event])
    assert len(matches) == 1


def test_no_start_time():
    entry = PlaylistEntry(
        name="ESPN+ 11: Some Event @ Jul 30 12:00PM ET",
        stream_url="http://example.com/stream",
        start_time=None,
    )
    event = make_event("Some Event")
    matches = match_events([entry], [event])
    assert len(matches) == 1


def test_fuzzy_match_fallback():
    entry = make_entry("ESPN+ 05: LA Lakers vs Boston Celtics @ Jul 30 7:00PM ET")
    event1 = make_event("New York Knicks vs Miami Heat")
    event2 = make_event("LA Lakers vs Boston Celtics")
    matches = match_events([entry], [event1, event2])
    assert len(matches) == 1
    assert matches[0][1]["title"] == "LA Lakers vs Boston Celtics"


def test_no_match():
    entry = make_entry("ESPN+ 99: Completely Different Event @ Jul 30 8:00PM ET")
    event = make_event("Unrelated Show")
    matches = match_events([entry], [event])
    assert len(matches) == 0


def test_extract_core_title_basic():
    result = extract_core_title("ESPN+ 27: Australia vs. USA Women's National Team @ Jul 30 8:00PM ET")
    assert result == "Australia vs. USA Women's National Team"


def test_extract_core_title_no_prefix():
    result = extract_core_title("Just a regular name")
    assert result == "Just a regular name"


def test_extract_core_title_with_league():
    result = extract_core_title("ESPN+ 123: MLB: Yankees vs Red Sox @ 7:00 PM @ Jul 30")
    assert result == "MLB: Yankees vs Red Sox"
