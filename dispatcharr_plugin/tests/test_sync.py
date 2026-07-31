import sys
import types
from types import SimpleNamespace

from dispatcharr_plugin.playlist import PlaylistEntry
from dispatcharr_plugin.sync import (
    assign_epg_data,
    channel_sort_key,
    target_channel_number,
    trigger_refresh_and_wait,
    upsert_epg_rows,
    wait_for_epg_refresh,
)


def make_entry(name: str) -> PlaylistEntry:
    return PlaylistEntry(name=name, stream_url="http://example.com/stream")


def test_target_channel_number():
    assert target_channel_number(make_entry("ESPN+ 1: Game @ Jul 31 7:00 PM"), 900) == 900.0
    assert target_channel_number(make_entry("ESPN+ 5: Game @ Jul 31 7:00 PM"), 900) == 904.0
    assert target_channel_number(make_entry("ESPN+ 12: Game @ Jul 31 7:00 PM"), 950.5) == 961.5


def test_target_channel_number_no_index():
    assert target_channel_number(make_entry("Not ESPN+"), 900) is None


def test_channel_sort_key_orders_by_index():
    e10 = make_entry("ESPN+ 10: Game @ Jul 31 7:00 PM")
    e5 = make_entry("ESPN+ 5: Game @ Jul 31 7:00 PM")
    plain = make_entry("Regular Channel")

    ordered = sorted([(e10, {}), (plain, {}), (e5, {})], key=channel_sort_key)
    assert [i[0].name for i in ordered] == [
        "ESPN+ 5: Game @ Jul 31 7:00 PM",
        "ESPN+ 10: Game @ Jul 31 7:00 PM",
        "Regular Channel",
    ]


class _QS:
    def __init__(self, rows):
        self._rows = rows

    def only(self, *fields):
        return self

    def first(self):
        return self._rows[0] if self._rows else None


class _Objects:
    def __init__(self, row_getter):
        self._row_getter = row_getter

    def filter(self, **kwargs):
        return _QS(self._row_getter())


class _EPGSource:
    STATUS_SUCCESS = "success"
    STATUS_ERROR = "error"
    STATUS_DISABLED = "disabled"
    objects = _Objects(lambda: [])


class _ValuesListQS:
    def __init__(self, getter):
        self._getter = getter

    def values_list(self, *fields, flat=False):
        return self._getter()


class _EPGDataManager:
    def __init__(self, tvg_ids_getter=None):
        self._getter = tvg_ids_getter or (lambda: [])
        self.rows = {}
        self.next_id = 1

    def filter(self, **kwargs):
        return _ValuesListQS(self._getter)

    def update_or_create(self, epg_source=None, tvg_id=None, defaults=None):
        key = (getattr(epg_source, "id", epg_source), tvg_id)
        defaults = defaults or {}
        if key in self.rows:
            row = self.rows[key]
            if "name" in defaults:
                row.name = defaults["name"]
            return row, False
        row = SimpleNamespace(
            id=self.next_id,
            tvg_id=tvg_id,
            name=defaults.get("name", ""),
            epg_source=epg_source,
        )
        self.rows[key] = row
        self.next_id += 1
        return row, True


class _EPGData:
    class _meta:
        @staticmethod
        def get_field(name):
            if name == "name":
                return SimpleNamespace(max_length=512)
            return SimpleNamespace(max_length=None)

    objects = None


def install_fake_epg_models(monkeypatch, source_row_getter, epg_tvg_ids_getter=None):
    mod_models = types.ModuleType("apps.epg.models")
    mod_models.EPGSource = _EPGSource
    mod_models.EPGData = _EPGData
    _EPGSource.objects = _Objects(source_row_getter)
    _EPGData.objects = _EPGDataManager(epg_tvg_ids_getter)
    monkeypatch.setitem(sys.modules, "apps", types.ModuleType("apps"))
    monkeypatch.setitem(sys.modules, "apps.epg", types.ModuleType("apps.epg"))
    monkeypatch.setitem(sys.modules, "apps.epg.models", mod_models)


def install_fake_epg_tasks(monkeypatch, delay_stub):
    mod_tasks = types.ModuleType("apps.epg.tasks")
    mod_tasks.refresh_epg_data = delay_stub
    monkeypatch.setitem(sys.modules, "apps.epg.tasks", mod_tasks)


SUCCESS_MSG = "Parsed 81 programs for 27 channels (skipped 0 programs for 0 unmapped channels)"


def test_wait_for_epg_refresh_success(monkeypatch):
    state = {"n": 0}

    def getter():
        state["n"] += 1
        if state["n"] == 1:
            return [SimpleNamespace(status="parsing", last_message="")]
        return [SimpleNamespace(status="success", last_message=SUCCESS_MSG)]

    install_fake_epg_models(monkeypatch, getter)
    assert wait_for_epg_refresh(34, timeout=2, interval=0.01) is True


def test_wait_for_epg_refresh_error(monkeypatch):
    def getter():
        return [SimpleNamespace(status="error", last_message="boom")]

    install_fake_epg_models(monkeypatch, getter)
    assert wait_for_epg_refresh(34, timeout=2, interval=0.01) is False


def test_wait_for_epg_refresh_timeout(monkeypatch):
    def getter():
        return [SimpleNamespace(status="parsing", last_message="")]

    install_fake_epg_models(monkeypatch, getter)
    assert wait_for_epg_refresh(34, timeout=0.05, interval=0.01) is False


def test_wait_for_epg_refresh_success_requires_programs_message(monkeypatch):
    def getter():
        return [SimpleNamespace(status="success", last_message="Successfully parsed 5 channels")]

    install_fake_epg_models(monkeypatch, getter)
    assert wait_for_epg_refresh(34, timeout=0.05, interval=0.01) is False


def test_upsert_epg_rows_creates_and_updates(monkeypatch):
    source = SimpleNamespace(id=39)
    entries = [
        (make_entry("ESPN+ 1: Game @ Jul 31 7:00 PM"), {}),
        (make_entry("ESPN+ 5: Game @ Jul 31 7:00 PM"), {}),
    ]
    install_fake_epg_models(monkeypatch, lambda: [])
    rows = upsert_epg_rows(source, entries, prefix="ESPN+")
    assert len(rows) == 2
    assert all(tvg.startswith("ESPN+") for tvg in rows)
    assert all(row.name for row in rows.values())

    rows2 = upsert_epg_rows(source, entries, prefix="ESPN+")
    assert set(rows2) == set(rows)
    assert len(_EPGData.objects.rows) == 2


def test_upsert_epg_rows_truncates_name(monkeypatch):
    source = SimpleNamespace(id=39)
    long_name = "ESPN+ 1: " + ("x" * 600)
    install_fake_epg_models(monkeypatch, lambda: [])
    rows = upsert_epg_rows(source, [(make_entry(long_name), {})], prefix="ESPN+")
    assert len(rows) == 1
    assert all(len(r.name) <= 512 for r in rows.values())


class _FakeChannel:
    def __init__(self, epg_data_id=None):
        self.epg_data_id = epg_data_id
        self.epg_data = None
        self.saved = []

    def save(self, update_fields=None):
        if self.epg_data is not None:
            self.epg_data_id = self.epg_data.id
        self.saved.append(update_fields)


def test_assign_epg_data_sets_matching_rows():
    row_a = SimpleNamespace(id=10)
    row_b = SimpleNamespace(id=11)
    ch_a = _FakeChannel()
    ch_b = _FakeChannel(epg_data_id=11)
    ch_c = _FakeChannel()

    n = assign_epg_data({"A": ch_a, "B": ch_b, "C": ch_c}, {"A": row_a, "B": row_b})
    assert n == 1
    assert ch_a.epg_data is row_a
    assert ch_a.saved == [["epg_data"]]
    assert ch_b.epg_data is None
    assert ch_c.epg_data is None

    assert assign_epg_data({"A": ch_a}, {"A": row_a}) == 0


def make_delayer():
    calls = []
    delayer = SimpleNamespace()
    delayer.delay = lambda source_id, force=False: calls.append((source_id, force))
    return delayer, calls


def test_trigger_refresh_success_first_try(monkeypatch):
    delayer, calls = make_delayer()
    install_fake_epg_models(monkeypatch, lambda: [SimpleNamespace(status="parsing", last_message="")])
    install_fake_epg_tasks(monkeypatch, delayer)
    monkeypatch.setattr("dispatcharr_plugin.sync.wait_for_epg_refresh", lambda source_id: True)
    assert trigger_refresh_and_wait(39) is True
    assert calls == [(39, True)]


def test_trigger_refresh_retries_on_timeout(monkeypatch):
    delayer, calls = make_delayer()
    install_fake_epg_models(monkeypatch, lambda: [SimpleNamespace(status="parsing", last_message="")])
    install_fake_epg_tasks(monkeypatch, delayer)
    results = iter([False, True])
    monkeypatch.setattr("dispatcharr_plugin.sync.wait_for_epg_refresh", lambda source_id: next(results))
    assert trigger_refresh_and_wait(39) is True
    assert calls == [(39, True), (39, True)]


def test_trigger_refresh_no_retry_on_error(monkeypatch):
    delayer, calls = make_delayer()
    install_fake_epg_models(monkeypatch, lambda: [SimpleNamespace(status="error", last_message="boom")])
    install_fake_epg_tasks(monkeypatch, delayer)
    monkeypatch.setattr("dispatcharr_plugin.sync.wait_for_epg_refresh", lambda source_id: False)
    assert trigger_refresh_and_wait(39) is False
    assert calls == [(39, True)]
