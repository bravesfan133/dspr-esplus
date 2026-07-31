from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from dispatcharr_plugin.engine import get_espn_days, merged_settings, run_once, validate_settings
from dispatcharr_plugin.state import State


def test_get_espn_days_today():
    days = get_espn_days({"espn_date": "today", "look_ahead_days": 0})
    assert days == [datetime.now(ZoneInfo("US/Eastern")).strftime("%Y-%m-%d")]


def test_get_espn_days_look_ahead_distinct():
    days = get_espn_days({"espn_date": "today", "look_ahead_days": 2})
    assert len(days) == 3
    assert len(set(days)) == 3


def test_get_espn_days_look_ahead_values():
    now_et = datetime.now(ZoneInfo("US/Eastern"))
    expected = [
        now_et.strftime("%Y-%m-%d"),
        (now_et + timedelta(days=1)).strftime("%Y-%m-%d"),
    ]
    assert get_espn_days({"espn_date": "today", "look_ahead_days": 1}) == expected


def test_get_espn_days_explicit_date():
    assert get_espn_days({"espn_date": "2026-08-01"}) == ["2026-08-01"]


def test_merged_settings_defaults():
    merged = merged_settings({})
    assert merged["channel_number_start"] == 900
    assert merged["min_similarity"] == 0.85
    assert merged["look_ahead_days"] == 1
    assert merged["auto_refresh"] is True


def test_merged_settings_overrides():
    merged = merged_settings({"look_ahead_days": 3, "auto_refresh": False})
    assert merged["look_ahead_days"] == 3
    assert merged["auto_refresh"] is False
    assert merged["keyword"] == "ESPN+"


def test_validate_settings_without_django():
    result = validate_settings({})
    assert result["status"] == "error"
    assert any("Dispatcharr" in e for e in result["errors"])


def espn_streams_for_day(day_iso: str) -> list[dict]:
    d = datetime.strptime(day_iso, "%Y-%m-%d")
    name = f"ESPN+ 1: NBA: Lakers vs Celtics @ 7:00 PM @ {d.strftime('%b')} {d.day}"
    return [
        {
            "id": 1,
            "name": name,
            "url": "http://example.com/stream",
            "tvg_id": None,
            "logo_url": None,
            "channel_group": None,
        }
    ]


def espn_event_for_day(day_iso: str) -> dict:
    start = datetime.fromisoformat(f"{day_iso}T19:00:00-04:00")
    end = datetime.fromisoformat(f"{day_iso}T21:00:00-04:00")
    return {
        "title": "Lakers vs Celtics",
        "short_name": "Lakers vs Celtics",
        "start_time": start.isoformat(),
        "end_time": end.isoformat(),
        "start_timestamp": int(start.timestamp()),
        "end_timestamp": int(end.timestamp()),
        "sport": "Basketball",
        "league": "NBA",
        "subcategory": "NBA Basketball",
        "is_studio": False,
        "image_url": "",
        "id": "1",
    }


def patch_state(monkeypatch, tmp_path):
    state = State(base_dir=str(tmp_path / "state"))
    monkeypatch.setattr("dispatcharr_plugin.engine.State", lambda: state)
    return state


def test_run_once_skips_when_nothing_changed(monkeypatch, tmp_path):
    from dispatcharr_plugin import engine

    days = get_espn_days({})
    streams = espn_streams_for_day(days[0])
    patch_state(monkeypatch, tmp_path)
    monkeypatch.setattr("dispatcharr_plugin.sync.list_streams", lambda: streams)
    monkeypatch.setattr(
        "dispatcharr_plugin.engine.fetch_espn_plus_schedule",
        lambda day_iso: [espn_event_for_day(day_iso)],
    )
    monkeypatch.setattr(
        "dispatcharr_plugin.sync.sync_to_dispatcharr",
        lambda matches, settings: {"associated": len(matches)},
    )

    first = run_once({})
    assert first["status"] == "ok"
    assert first["matches"] == 1

    second = run_once({})
    assert second["status"] == "skipped"


def test_run_once_runs_when_matches_change(monkeypatch, tmp_path):
    from dispatcharr_plugin import engine

    days = get_espn_days({})
    streams = espn_streams_for_day(days[0])
    patch_state(monkeypatch, tmp_path)
    monkeypatch.setattr("dispatcharr_plugin.sync.list_streams", lambda: streams)
    calls = {"n": 0}

    def schedule(day_iso):
        calls["n"] += 1
        if calls["n"] == 1:
            return [espn_event_for_day(day_iso)]
        ev = espn_event_for_day(day_iso)
        start = datetime.fromisoformat(ev["start_time"]) + timedelta(hours=1)
        return [dict(ev, start_time=start.isoformat(), start_timestamp=int(start.timestamp()))]

    monkeypatch.setattr("dispatcharr_plugin.engine.fetch_espn_plus_schedule", schedule)
    monkeypatch.setattr(
        "dispatcharr_plugin.sync.sync_to_dispatcharr",
        lambda matches, settings: {"associated": len(matches)},
    )

    assert run_once({})["status"] == "ok"
    second = run_once({})
    assert second["status"] == "ok"
    assert second["matches"] == 1


def test_run_once_force_runs_even_when_unchanged(monkeypatch, tmp_path):
    from dispatcharr_plugin import engine

    days = get_espn_days({})
    streams = espn_streams_for_day(days[0])
    patch_state(monkeypatch, tmp_path)
    monkeypatch.setattr("dispatcharr_plugin.sync.list_streams", lambda: streams)
    monkeypatch.setattr(
        "dispatcharr_plugin.engine.fetch_espn_plus_schedule",
        lambda day_iso: [espn_event_for_day(day_iso)],
    )
    monkeypatch.setattr(
        "dispatcharr_plugin.sync.sync_to_dispatcharr",
        lambda matches, settings: {"associated": len(matches)},
    )

    assert run_once({})["status"] == "ok"
    assert run_once({})["status"] == "skipped"
    assert run_once({}, force=True)["status"] == "ok"


def test_run_once_dry_run_does_not_record_hash(monkeypatch, tmp_path):
    from dispatcharr_plugin import engine

    days = get_espn_days({})
    streams = espn_streams_for_day(days[0])
    state = patch_state(monkeypatch, tmp_path)
    monkeypatch.setattr("dispatcharr_plugin.sync.list_streams", lambda: streams)
    monkeypatch.setattr(
        "dispatcharr_plugin.engine.fetch_espn_plus_schedule",
        lambda day_iso: [espn_event_for_day(day_iso)],
    )
    monkeypatch.setattr(
        "dispatcharr_plugin.sync.sync_to_dispatcharr",
        lambda matches, settings: {"associated": len(matches)},
    )

    assert run_once({}, dry_run=True)["status"] == "ok"
    assert run_once({}, dry_run=True)["status"] == "ok"
    assert state.load_hash() is None


def test_run_once_dry_run_matches(monkeypatch, tmp_path):
    from dispatcharr_plugin import engine

    days = get_espn_days({})
    streams = espn_streams_for_day(days[0])
    patch_state(monkeypatch, tmp_path)
    monkeypatch.setattr("dispatcharr_plugin.sync.list_streams", lambda: streams)
    monkeypatch.setattr(
        "dispatcharr_plugin.engine.fetch_espn_plus_schedule",
        lambda day_iso: [espn_event_for_day(day_iso)],
    )

    result = run_once({}, dry_run=True)
    assert result["status"] == "ok"
    assert result["dry_run"] is True
    assert result["matches"] == 1


def test_run_once_no_matches(monkeypatch, tmp_path):
    from dispatcharr_plugin import engine

    days = get_espn_days({})
    streams = espn_streams_for_day(days[0])
    patch_state(monkeypatch, tmp_path)
    monkeypatch.setattr("dispatcharr_plugin.sync.list_streams", lambda: streams)
    monkeypatch.setattr(
        "dispatcharr_plugin.engine.fetch_espn_plus_schedule",
        lambda day_iso: [],
    )

    result = run_once({})
    assert result["status"] == "ok"
    assert result["matches"] == 0
    assert result["message"] == "No matches found"
    assert "days" in result
