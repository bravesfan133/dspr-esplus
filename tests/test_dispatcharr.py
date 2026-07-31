import asyncio
from datetime import datetime, timezone

import httpx

from src.config import Config
from src.dispatcharr import DispatcharrClient
from src.main import sync_to_dispatcharr
from src.playlist import PlaylistEntry
from src.xmltv_gen import get_channel_id


def make_entry(name: str, stream_id: int = 1) -> PlaylistEntry:
    return PlaylistEntry(
        name=name,
        stream_url="http://example.com/stream",
        tvg_name=name,
        stream_id=stream_id,
    )


def make_metadata() -> dict:
    start = datetime(2026, 7, 31, 19, 0, tzinfo=timezone.utc)
    end = datetime(2026, 7, 31, 21, 0, tzinfo=timezone.utc)
    return {
        "title": "Game",
        "short_name": "Game",
        "start_time": start.isoformat(),
        "end_time": end.isoformat(),
        "sport": "Baseball",
        "league": "MLB",
    }


def test_create_channel_sends_tvg_id():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = request.content
        return httpx.Response(201, json={"id": 10, "name": "ESPN+ 1: Game @ Jul 31 3:00PM ET"})

    client = DispatcharrClient(base_url="http://x")
    client._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    entry = make_entry("ESPN+ 1: Game @ Jul 31 3:00PM ET")
    import json
    asyncio.run(client.create_channel(entry, group_id=5, channel_number=900.0, tvg_id="ESPN+.X"))
    payload = json.loads(seen["body"])
    assert payload["tvg_id"] == "ESPN+.X"


def test_wait_for_epg_refresh_success():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(200, json=[{"id": 34, "status": "parsing", "last_message": ""}])
        return httpx.Response(200, json=[{"id": 34, "status": "success", "last_message": "Parsed 81 programs for 27 channels (skipped 0 programs for 0 unmapped channels)"}])

    client = DispatcharrClient(base_url="http://x")
    client._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    result = asyncio.run(client.wait_for_epg_refresh(34, timeout=10, interval=0.01))
    assert result is True


def test_wait_for_epg_refresh_timeout():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[{"id": 34, "status": "parsing", "last_message": ""}])

    client = DispatcharrClient(base_url="http://x")
    client._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    result = asyncio.run(client.wait_for_epg_refresh(34, timeout=0.05, interval=0.01))
    assert result is False


class FakeDispatcharr:
    def __init__(self, entries: list[PlaylistEntry]):
        self.entries = entries
        self.calls = []
        self.channel_ids = {i + 1: e for i, e in enumerate(entries)}
        self.xmltv_ids = [get_channel_id(e, prefix="ESPN+") for e in entries]
        self.source_id = 34

    async def get_profile_by_name(self, name):
        self.calls.append("get_profile_by_name")
        return {"id": 2, "name": name}

    async def get_or_create_group(self, group_name):
        self.calls.append("get_or_create_group")
        return 5

    async def get_channels(self, params=None):
        self.calls.append("get_channels")
        return []

    async def create_channel(self, entry, group_id=None, channel_number=None, tvg_id=None):
        self.calls.append(("create_channel", tvg_id))
        return {"id": self.channel_ids.get(len(self.calls), 1)}

    async def update_channel(self, channel_id, entry, group_id=None, tvg_id=None):
        self.calls.append(("update_channel", tvg_id))

    async def set_channel_number(self, channel_id, channel_number):
        self.calls.append("set_channel_number")

    async def bulk_add_channels_to_profile(self, channel_ids, profile_id, enabled=True):
        self.calls.append("bulk_add_channels_to_profile")

    async def upload_xmltv(self, name, source_type, xml_content, filename="espnplus_epg.xml"):
        self.calls.append("upload_xmltv")
        return {"id": self.source_id, "name": name}

    async def trigger_epg_refresh(self, source_id):
        self.calls.append(("trigger_epg_refresh", source_id))

    async def list_epg_data(self):
        self.calls.append("list_epg_data")
        return [{"id": i + 1, "tvg_id": tvg} for i, tvg in enumerate(self.xmltv_ids)]

    async def batch_set_epg(self, associations):
        self.calls.append(("batch_set_epg", len(associations)))

    async def wait_for_epg_refresh(self, source_id, timeout=90):
        self.calls.append(("wait_for_epg_refresh", source_id))
        return True


def test_sync_refreshes_after_mapping():
    entries = [
        make_entry("ESPN+ 1: Game One @ Jul 31 3:00PM ET", stream_id=1),
        make_entry("ESPN+ 2: Game Two @ Jul 31 5:00PM ET", stream_id=2),
    ]
    matches = [(e, make_metadata()) for e in entries]

    fake = FakeDispatcharr(entries)
    cfg = Config()
    cfg.epg.source_name = "ESPN+ EPG"
    cfg.epg.epg_group_name = "ESPN+"
    cfg.epg.channel_id_prefix = "ESPN+"

    asyncio.run(sync_to_dispatcharr(matches, cfg, fake, xmltv_path="output/espnplus_epg.xml"))

    refresh_calls = [c for c in fake.calls if c[0] == "trigger_epg_refresh"]
    assert len(refresh_calls) == 2

    batch_idx = next(i for i, c in enumerate(fake.calls) if c[0] == "batch_set_epg")
    second_refresh_idx = next(
        i for i, c in enumerate(fake.calls) if c[0] == "trigger_epg_refresh" and i > batch_idx
    )
    assert second_refresh_idx > batch_idx

    tvg_ids = [c[1] for c in fake.calls if c[0] == "create_channel"]
    assert tvg_ids == fake.xmltv_ids
