from datetime import datetime
from zoneinfo import ZoneInfo

from dispatcharr_plugin.playlist import (
    event_ends_after,
    extract_espn_datetime,
    extract_display_title,
    filter_entries_by_day,
    PlaylistEntry,
)


def test_extract_datetime_evening():
    name = "ESPN+ 123: MLB: Yankees vs Red Sox @ 7:00 PM @ Jul 30"
    dt = extract_espn_datetime(name)
    assert dt is not None
    assert dt.tzinfo.key == "US/Eastern"
    assert dt.hour == 19
    assert dt.minute == 0
    assert dt.month == 7


def test_extract_datetime_morning():
    name = "ESPN+ 456: NBA: Lakers vs Celtics @ 10:30 AM @ Aug 15"
    dt = extract_espn_datetime(name)
    assert dt is not None
    assert dt.hour == 10
    assert dt.minute == 30
    assert dt.month == 8
    assert dt.day == 15


def test_extract_datetime_noon():
    name = "ESPN+ 789: NFL: Chiefs vs 49ers @ 12:00 PM @ Sep 10"
    dt = extract_espn_datetime(name)
    assert dt is not None
    assert dt.hour == 12
    assert dt.minute == 0


def test_extract_datetime_midnight():
    name = "ESPN+ 101: NHL: Rangers vs Bruins @ 12:00 AM @ Oct 5"
    dt = extract_espn_datetime(name)
    assert dt is not None
    assert dt.hour == 0
    assert dt.minute == 0


def test_no_espn_plus():
    assert extract_espn_datetime("Some other channel") is None


def test_missing_time():
    assert extract_espn_datetime("ESPN+ 123: Game @ Jul 30") is None


def test_missing_date():
    assert extract_espn_datetime("ESPN+ 123: Game @ 7:00 PM") is None


def test_extract_display_title_with_league():
    name = "ESPN+ 123: MLB: Yankees vs Red Sox @ 7:00 PM @ Jul 30"
    title = extract_display_title(name)
    assert title is not None
    assert "MLB" in title or "Yankees" in title or "Red Sox" in title


def test_extract_display_title_without_league():
    name = "ESPN+ 456: Lakers vs Celtics @ 10:30 AM @ Aug 15"
    title = extract_display_title(name)
    assert title is not None
    assert "Lakers" in title
    assert "Celtics" in title


def test_et_conversion():
    name = "ESPN+ 1: MLB: Team A vs Team B @ 7:00 PM @ Jan 4"
    dt = extract_espn_datetime(name)
    assert dt is not None

    assert dt.tzinfo.key == "US/Eastern"
    assert dt.day == 4
    assert dt.hour == 19
    assert dt.minute == 0


def make_entry(name: str) -> PlaylistEntry:
    entry = PlaylistEntry(name=name, stream_url="http://example.com/stream")
    entry.start_time = extract_espn_datetime(name)
    return entry


def test_filter_entries_by_day_keeps_target_days():
    today = make_entry("ESPN+ 1: MLB: Team A vs Team B @ 7:00 PM @ Jul 31")
    tomorrow = make_entry("ESPN+ 2: NBA: Team C vs Team D @ 7:00 PM @ Aug 1")
    entries = [today, tomorrow]
    filtered = filter_entries_by_day(entries, ["2026-07-31", "2026-08-01"])
    assert filtered == [today, tomorrow]


def test_filter_entries_by_day_drops_off_day():
    yesterday = make_entry("ESPN+ 1: MLB: Team A vs Team B @ 7:00 PM @ Jul 30")
    today = make_entry("ESPN+ 2: NBA: Team C vs Team D @ 7:00 PM @ Jul 31")
    filtered = filter_entries_by_day([yesterday, today], ["2026-07-31"])
    assert filtered == [today]


def test_filter_entries_by_day_drops_undated():
    undated = PlaylistEntry(name="ESPN+ 3: Some Event", stream_url="http://example.com/stream")
    today = make_entry("ESPN+ 2: NBA: Team C vs Team D @ 7:00 PM @ Jul 31")
    filtered = filter_entries_by_day([undated, today], ["2026-07-31"])
    assert filtered == [today]


def make_event(start: datetime, end: datetime) -> dict:
    return {"start_time": start.isoformat(), "end_time": end.isoformat()}


def test_event_ends_after_crosses_boundary():
    eastern = ZoneInfo("US/Eastern")
    boundary = datetime(2026, 8, 1, 0, 0, tzinfo=eastern)
    start = datetime(2026, 7, 31, 23, 30, tzinfo=eastern)
    end = datetime(2026, 8, 1, 1, 0, tzinfo=eastern)
    assert event_ends_after([make_event(start, end)], start, boundary) is True


def test_event_ends_after_ends_before_boundary():
    eastern = ZoneInfo("US/Eastern")
    boundary = datetime(2026, 8, 1, 0, 0, tzinfo=eastern)
    start = datetime(2026, 7, 31, 18, 0, tzinfo=eastern)
    end = datetime(2026, 7, 31, 20, 0, tzinfo=eastern)
    assert event_ends_after([make_event(start, end)], start, boundary) is False


def test_event_ends_after_no_matching_start_time():
    eastern = ZoneInfo("US/Eastern")
    boundary = datetime(2026, 8, 1, 0, 0, tzinfo=eastern)
    event_start = datetime(2026, 7, 31, 18, 0, tzinfo=eastern)
    event_end = datetime(2026, 8, 1, 1, 0, tzinfo=eastern)
    query_start = datetime(2026, 7, 31, 19, 0, tzinfo=eastern)
    assert event_ends_after([make_event(event_start, event_end)], query_start, boundary) is False


def test_event_ends_after_missing_end_time():
    eastern = ZoneInfo("US/Eastern")
    boundary = datetime(2026, 8, 1, 0, 0, tzinfo=eastern)
    start = datetime(2026, 7, 31, 23, 30, tzinfo=eastern)
    event = {"start_time": start.isoformat(), "end_time": None}
    assert event_ends_after([event], start, boundary) is False


def test_event_ends_after_empty_events():
    eastern = ZoneInfo("US/Eastern")
    boundary = datetime(2026, 8, 1, 0, 0, tzinfo=eastern)
    start = datetime(2026, 7, 31, 23, 30, tzinfo=eastern)
    assert event_ends_after([], start, boundary) is False
