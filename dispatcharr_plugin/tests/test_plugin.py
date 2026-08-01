import json
from pathlib import Path

from dispatcharr_plugin.plugin import Plugin


def test_no_select_option_with_empty_value():
    for field in Plugin.fields:
        if field.get("type") != "select":
            continue
        for option in field.get("options", []):
            assert str(option.get("value", "")) != ""


def test_channels_dvr_source_fields_are_strings():
    by_id = {f["id"]: f for f in Plugin.fields}
    assert by_id["channels_dvr_m3u_source"]["type"] == "string"
    assert by_id["channels_dvr_epg_lineup"]["type"] == "string"


def test_no_load_sources_action():
    assert "load_channels_dvr_sources" not in {a["id"] for a in Plugin.actions}


def test_manifest_matches_class():
    manifest = json.loads(
        (Path(__file__).resolve().parent.parent / "plugin.json").read_text()
    )
    plugin = Plugin()
    assert manifest["version"] == plugin.version
    assert [f["id"] for f in manifest["fields"]] == [f["id"] for f in plugin.fields]
    assert [a["id"] for a in manifest["actions"]] == [a["id"] for a in plugin.actions]
