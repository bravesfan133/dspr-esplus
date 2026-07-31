from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from src.config import Config
from src.main import get_espn_days


def test_get_espn_days_today():
    cfg = Config()
    cfg.espn.date = "today"
    cfg.espn.look_ahead_days = 0
    days = get_espn_days(cfg)
    assert days == [datetime.now(ZoneInfo("US/Eastern")).strftime("%Y-%m-%d")]


def test_get_espn_days_look_ahead_distinct():
    cfg = Config()
    cfg.espn.date = "today"
    cfg.espn.look_ahead_days = 2
    days = get_espn_days(cfg)
    assert len(days) == 3
    assert len(set(days)) == 3


def test_get_espn_days_look_ahead_values():
    cfg = Config()
    cfg.espn.date = "today"
    cfg.espn.look_ahead_days = 1
    now_et = datetime.now(ZoneInfo("US/Eastern"))
    expected = [
        now_et.strftime("%Y-%m-%d"),
        (now_et + timedelta(days=1)).strftime("%Y-%m-%d"),
    ]
    assert get_espn_days(cfg) == expected


def test_get_espn_days_explicit_date():
    cfg = Config()
    cfg.espn.date = "2026-08-01"
    assert get_espn_days(cfg) == ["2026-08-01"]
