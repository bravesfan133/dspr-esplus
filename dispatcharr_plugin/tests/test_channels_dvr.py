import sys
import types

from dispatcharr_plugin.channels_dvr import (
    derive_epg_lineup_name,
    is_reachable,
    list_sources,
    normalize_base_url,
    refresh_and_report,
    refresh_epg_lineup,
    refresh_m3u_source,
)


class FakeResponse:
    def __init__(self, status_code=200, payload=None, exc=None):
        self.status_code = status_code
        self._payload = payload
        self._exc = exc

    def raise_for_status(self):
        if self._exc is not None:
            raise self._exc
        if self.status_code >= 400:
            raise ConnectionError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


def install_fake_requests(monkeypatch, *, get=None, post=None, put=None):
    mod = types.ModuleType("requests")
    mod.get = get or (lambda *a, **k: FakeResponse(200, {}))
    mod.post = post or (lambda *a, **k: FakeResponse(200, {}))
    mod.put = put or (lambda *a, **k: FakeResponse(200, {}))
    monkeypatch.setitem(sys.modules, "requests", mod)


def test_normalize_base_url():
    assert normalize_base_url("192.168.0.168:8089") == "http://192.168.0.168:8089"
    assert normalize_base_url("http://192.168.0.168:8089/") == "http://192.168.0.168:8089"
    assert normalize_base_url("  https://dvr.example.com  ") == "https://dvr.example.com"
    assert normalize_base_url("") == ""


def test_derive_epg_lineup_name():
    assert derive_epg_lineup_name("Platinum and EPG") == "XMLTV-Platinum and EPG"
    assert derive_epg_lineup_name("  ABC  ") == "XMLTV-ABC"


def test_is_reachable_ok(monkeypatch):
    calls = []

    def get(url, timeout=None):
        calls.append(url)
        return FakeResponse(200, {"status": "ok"})

    install_fake_requests(monkeypatch, get=get)
    assert is_reachable("http://dvr") is None
    assert calls == ["http://dvr/status"]


def test_is_reachable_failure(monkeypatch):
    def get(url, timeout=None):
        raise ConnectionError("refused")

    install_fake_requests(monkeypatch, get=get)
    assert "refused" in is_reachable("http://dvr")


def test_is_reachable_empty_url(monkeypatch):
    install_fake_requests(monkeypatch)
    assert "empty" in is_reachable("")


def test_list_sources_parses_devices(monkeypatch):
    def get(url, timeout=None):
        if url.endswith("/devices"):
            return FakeResponse(
                200,
                {
                    "Devices": [
                        {"DeviceID": "M3U:abcdef", "FriendlyName": "Platinum and EPG"},
                        {"DeviceID": "HDHOMERUN:123", "FriendlyName": "Tuner"},
                    ]
                },
            )
        return FakeResponse(200, {"M3U:abcdef": "XMLTV-PlatinumandEPG"})

    install_fake_requests(monkeypatch, get=get)
    result = list_sources("http://dvr")
    assert result["m3u_sources"] == [
        {"name": "Platinum and EPG", "device_id": "M3U:abcdef"}
    ]
    assert result["epg_lineups"] == ["XMLTV-PlatinumandEPG"]
    assert result["device_to_lineup"] == {"M3U:abcdef": "XMLTV-PlatinumandEPG"}


def test_list_sources_tolerates_errors(monkeypatch):
    def get(url, timeout=None):
        raise ConnectionError("down")

    install_fake_requests(monkeypatch, get=get)
    result = list_sources("http://dvr")
    assert result == {"m3u_sources": [], "epg_lineups": [], "device_to_lineup": {}}


def test_refresh_m3u_source_success(monkeypatch):
    calls = []

    def post(url, timeout=None):
        calls.append(url)
        return FakeResponse(200, {})

    install_fake_requests(monkeypatch, post=post)
    assert refresh_m3u_source("http://dvr", "Platinum and EPG") is True
    assert calls == ["http://dvr/providers/m3u/sources/Platinum%20and%20EPG/refresh"]


def test_refresh_m3u_source_retries_with_device_id(monkeypatch):
    calls = []

    def post(url, timeout=None):
        calls.append(url)
        if url.endswith("Platinum/refresh"):
            return FakeResponse(404, {})
        return FakeResponse(200, {})

    install_fake_requests(monkeypatch, post=post)
    assert refresh_m3u_source("http://dvr", "Platinum", device_id="M3U:abc") is True
    assert calls == [
        "http://dvr/providers/m3u/sources/Platinum/refresh",
        "http://dvr/providers/m3u/sources/M3U%3Aabc/refresh",
    ]


def test_refresh_m3u_source_failure(monkeypatch):
    def post(url, timeout=None):
        raise ConnectionError("down")

    install_fake_requests(monkeypatch, post=post)
    assert refresh_m3u_source("http://dvr", "Platinum") is False


def test_refresh_m3u_source_empty_name(monkeypatch):
    calls = []

    def post(url, timeout=None):
        calls.append(url)
        return FakeResponse(200, {})

    install_fake_requests(monkeypatch, post=post)
    assert refresh_m3u_source("http://dvr", "") is False
    assert calls == []


def test_refresh_epg_lineup_success(monkeypatch):
    calls = []

    def put(url, timeout=None):
        calls.append(url)
        return FakeResponse(200, {})

    install_fake_requests(monkeypatch, put=put)
    assert refresh_epg_lineup("http://dvr", "XMLTV-Platinum and EPG") is True
    assert calls == ["http://dvr/dvr/lineups/XMLTV-Platinum%20and%20EPG"]


def test_refresh_epg_lineup_failure(monkeypatch):
    def put(url, timeout=None):
        raise ConnectionError("down")

    install_fake_requests(monkeypatch, put=put)
    assert refresh_epg_lineup("http://dvr", "XMLTV-Platinum") is False


def test_refresh_epg_lineup_empty_name(monkeypatch):
    calls = []

    def put(url, timeout=None):
        calls.append(url)
        return FakeResponse(200, {})

    install_fake_requests(monkeypatch, put=put)
    assert refresh_epg_lineup("http://dvr", "") is False
    assert calls == []


def test_refresh_and_report_posts_m3u_and_puts_epg(monkeypatch):
    calls = []

    def post(url, timeout=None):
        calls.append(("POST", url))
        return FakeResponse(200, {})

    def put(url, timeout=None):
        calls.append(("PUT", url))
        return FakeResponse(200, {})

    install_fake_requests(monkeypatch, post=post, put=put)
    result = refresh_and_report("http://dvr", "PlatinumandEPG")
    assert result["status"] == "ok"
    assert ("POST", "http://dvr/providers/m3u/sources/PlatinumandEPG/refresh") in calls
    assert ("PUT", "http://dvr/dvr/lineups/XMLTV-PlatinumandEPG") in calls
    assert result["details"] == [
        "POST http://dvr/providers/m3u/sources/PlatinumandEPG/refresh -> 200",
        "PUT http://dvr/dvr/lineups/XMLTV-PlatinumandEPG -> 200",
    ]


def test_refresh_and_report_reports_failure_with_urls(monkeypatch):
    calls = []

    def post(url, timeout=None):
        calls.append(("POST", url))
        return FakeResponse(404, {})

    def put(url, timeout=None):
        calls.append(("PUT", url))
        raise ConnectionError("refused")

    install_fake_requests(monkeypatch, post=post, put=put)
    result = refresh_and_report("http://dvr", "PlatinumandEPG", lineup_name="XMLTV-PlatinumandEPG")
    assert result["status"] == "error"
    assert any("POST" in d for d in result["details"])
    assert any("PUT" in d for d in result["details"])
    assert result["details"][0].endswith("HTTP 404")


def test_refresh_and_report_missing_source(monkeypatch):
    install_fake_requests(monkeypatch)
    result = refresh_and_report("http://dvr", "")
    assert result["status"] == "error"
    assert "source" in result["message"]
