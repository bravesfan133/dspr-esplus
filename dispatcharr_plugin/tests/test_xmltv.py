from datetime import datetime, timezone
from lxml import etree

from dispatcharr_plugin.xmltv_gen import generate_xmltv, get_channel_id, _build_channel_id, _format_xmltv_time
from dispatcharr_plugin.playlist import PlaylistEntry


def make_entry(name: str) -> PlaylistEntry:
    return PlaylistEntry(
        name=name,
        stream_url="http://example.com/stream",
        tvg_name=name,
        group="USA|ESPN+",
    )


def make_metadata(title: str, start: str, end: str) -> dict:
    return {
        "title": title,
        "short_name": title,
        "start_time": start,
        "end_time": end,
        "sport": "Basketball",
        "league": "NBA",
        "subcategory": "NBA Basketball",
        "is_studio": False,
        "image_url": "http://example.com/icon.png",
        "description": "Big game tonight",
    }


def test_three_programmes_per_channel():
    entry = make_entry("NBA: Lakers vs Celtics")
    metadata = make_metadata(
        "Lakers vs Celtics",
        "2024-01-15T20:00:00+00:00",
        "2024-01-15T22:00:00+00:00",
    )

    xml = generate_xmltv([(entry, metadata)])
    root = etree.fromstring(xml.encode("utf-8"))
    progs = root.findall("programme")
    assert len(progs) == 3


def test_upcoming_title_prefix():
    entry = make_entry("NBA: Lakers vs Celtics")
    metadata = make_metadata(
        "Lakers vs Celtics",
        "2024-01-15T20:00:00+00:00",
        "2024-01-15T22:00:00+00:00",
    )
    xml = generate_xmltv([(entry, metadata)])
    root = etree.fromstring(xml.encode("utf-8"))
    progs = root.findall("programme")
    titles = [p.find("title").text for p in progs]
    assert titles[0] == "UPCOMING: ESPN+: Lakers vs Celtics"
    assert titles[1] == "ESPN+: Lakers vs Celtics"
    assert titles[2] == "ENDED: ESPN+: Lakers vs Celtics"


def test_title_prefix_on_all_programmes():
    entry = make_entry("NBA: Lakers vs Celtics")
    metadata = make_metadata(
        "Lakers vs Celtics",
        "2024-01-15T20:00:00+00:00",
        "2024-01-15T22:00:00+00:00",
    )
    xml = generate_xmltv([(entry, metadata)])
    root = etree.fromstring(xml.encode("utf-8"))
    progs = root.findall("programme")
    assert progs[1].find("title").text.startswith("ESPN+:")
    for prog in progs:
        assert "ESPN+:" in prog.find("title").text


def test_categories_on_all_three_programmes():
    entry = make_entry("NBA: Lakers vs Celtics")
    metadata = make_metadata(
        "Lakers vs Celtics",
        "2024-01-15T20:00:00+00:00",
        "2024-01-15T22:00:00+00:00",
    )
    xml = generate_xmltv([(entry, metadata)])
    root = etree.fromstring(xml.encode("utf-8"))
    expected = ["Sports", "Sports Event", "Basketball", "NBA", "NBA Basketball"]
    for prog in root.findall("programme"):
        cats = [c.text for c in prog.findall("category")]
        assert cats == expected


def test_no_sports_event_category_when_studio():
    entry = make_entry("NBA: Lakers vs Celtics")
    metadata = make_metadata(
        "Lakers vs Celtics",
        "2024-01-15T20:00:00+00:00",
        "2024-01-15T22:00:00+00:00",
    )
    metadata["is_studio"] = True
    xml = generate_xmltv([(entry, metadata)])
    root = etree.fromstring(xml.encode("utf-8"))
    for prog in root.findall("programme"):
        cats = [c.text for c in prog.findall("category")]
        assert "Sports Event" not in cats
        assert "Sports" in cats


def test_desc_only_on_real_programme():
    entry = make_entry("NBA: Lakers vs Celtics")
    metadata = make_metadata(
        "Lakers vs Celtics",
        "2024-01-15T20:00:00+00:00",
        "2024-01-15T22:00:00+00:00",
    )
    xml = generate_xmltv([(entry, metadata)])
    root = etree.fromstring(xml.encode("utf-8"))
    progs = root.findall("programme")
    assert progs[0].find("desc") is None
    assert progs[1].find("desc") is not None
    assert progs[2].find("desc") is None


def test_upcoming_ends_at_real_start():
    entry = make_entry("NBA: Lakers vs Celtics")
    metadata = make_metadata(
        "Lakers vs Celtics",
        "2024-01-15T20:00:00+00:00",
        "2024-01-15T22:00:00+00:00",
    )
    xml = generate_xmltv([(entry, metadata)])
    root = etree.fromstring(xml.encode("utf-8"))
    progs = root.findall("programme")
    assert progs[0].get("stop") == progs[1].get("start")


def test_ended_starts_at_real_end():
    entry = make_entry("NBA: Lakers vs Celtics")
    metadata = make_metadata(
        "Lakers vs Celtics",
        "2024-01-15T20:00:00+00:00",
        "2024-01-15T22:00:00+00:00",
    )
    xml = generate_xmltv([(entry, metadata)])
    root = etree.fromstring(xml.encode("utf-8"))
    progs = root.findall("programme")
    assert progs[1].get("stop") == progs[2].get("start")


def test_real_programme_no_prefix():
    entry = make_entry("NBA: Lakers vs Celtics")
    metadata = make_metadata(
        "Lakers vs Celtics",
        "2024-01-15T20:00:00+00:00",
        "2024-01-15T22:00:00+00:00",
    )
    xml = generate_xmltv([(entry, metadata)])
    root = etree.fromstring(xml.encode("utf-8"))
    progs = root.findall("programme")
    title = progs[1].find("title").text
    assert not title.startswith("UPCOMING:")
    assert not title.startswith("ENDED:")


def test_no_programmes_when_real_times_missing():
    entry = make_entry("NBA: Lakers vs Celtics")
    metadata = make_metadata(
        "Lakers vs Celtics",
        "2024-01-15T20:00:00+00:00",
        "2024-01-15T22:00:00+00:00",
    )
    del metadata["start_time"]
    del metadata["end_time"]
    xml = generate_xmltv([(entry, metadata)])
    root = etree.fromstring(xml.encode("utf-8"))
    progs = root.findall("programme")
    assert len(progs) == 0


def test_only_live_on_middle_programme():
    entry = make_entry("NBA: Lakers vs Celtics")
    metadata = make_metadata(
        "Lakers vs Celtics",
        "2024-01-15T20:00:00+00:00",
        "2024-01-15T22:00:00+00:00",
    )
    xml = generate_xmltv([(entry, metadata)])
    root = etree.fromstring(xml.encode("utf-8"))
    progs = root.findall("programme")
    assert progs[0].find("live") is None
    assert progs[1].find("live") is not None
    assert progs[2].find("live") is None


def test_new_and_premiere_only_on_real_programme():
    entry = make_entry("NBA: Lakers vs Celtics")
    metadata = make_metadata(
        "Lakers vs Celtics",
        "2024-01-15T20:00:00+00:00",
        "2024-01-15T22:00:00+00:00",
    )
    xml = generate_xmltv([(entry, metadata)])
    root = etree.fromstring(xml.encode("utf-8"))
    progs = root.findall("programme")
    assert progs[0].find("new") is None
    assert progs[1].find("new") is not None
    assert progs[2].find("new") is None
    assert progs[0].find("premiere") is None
    assert progs[1].find("premiere") is not None
    assert progs[2].find("premiere") is None


def test_no_live_when_studio():
    entry = make_entry("NBA: Lakers vs Celtics")
    metadata = make_metadata(
        "Lakers vs Celtics",
        "2024-01-15T20:00:00+00:00",
        "2024-01-15T22:00:00+00:00",
    )
    metadata["is_studio"] = True
    xml = generate_xmltv([(entry, metadata)])
    root = etree.fromstring(xml.encode("utf-8"))
    progs = root.findall("programme")
    assert progs[1].find("live") is None
    assert progs[1].find("new") is not None


def test_icons_on_all_three_programmes():
    entry = make_entry("NBA: Lakers vs Celtics")
    metadata = make_metadata(
        "Lakers vs Celtics",
        "2024-01-15T20:00:00+00:00",
        "2024-01-15T22:00:00+00:00",
    )
    xml = generate_xmltv([(entry, metadata)])
    root = etree.fromstring(xml.encode("utf-8"))
    prog_icons = root.findall(".//programme/icon")
    assert len(prog_icons) == 3


def test_no_icons_when_image_url_missing():
    entry = make_entry("NBA: Lakers vs Celtics")
    metadata = make_metadata(
        "Lakers vs Celtics",
        "2024-01-15T20:00:00+00:00",
        "2024-01-15T22:00:00+00:00",
    )
    del metadata["image_url"]
    xml = generate_xmltv([(entry, metadata)])
    root = etree.fromstring(xml.encode("utf-8"))
    prog_icons = root.findall(".//programme/icon")
    assert len(prog_icons) == 0


def test_channel_icon_when_tvg_logo_present():
    entry = PlaylistEntry(
        name="NBA: Lakers vs Celtics",
        stream_url="http://example.com/stream",
        tvg_logo="http://example.com/logo.png",
        tvg_name="NBA: Lakers vs Celtics",
        group="USA|ESPN+",
    )
    metadata = make_metadata(
        "Lakers vs Celtics",
        "2024-01-15T20:00:00+00:00",
        "2024-01-15T22:00:00+00:00",
    )
    xml = generate_xmltv([(entry, metadata)])
    root = etree.fromstring(xml.encode("utf-8"))
    ch_icons = root.findall(".//channel/icon")
    assert len(ch_icons) == 1
    assert ch_icons[0].get("src") == "http://example.com/logo.png"


def test_channel_no_icon_when_tvg_logo_missing():
    entry = make_entry("NBA: Lakers vs Celtics")
    metadata = make_metadata(
        "Lakers vs Celtics",
        "2024-01-15T20:00:00+00:00",
        "2024-01-15T22:00:00+00:00",
    )
    xml = generate_xmltv([(entry, metadata)])
    root = etree.fromstring(xml.encode("utf-8"))
    ch_icons = root.findall(".//channel/icon")
    assert len(ch_icons) == 0


def test_channel_id_format():
    entry = make_entry("NBA: Lakers @ Celtics")
    cid = get_channel_id(entry)
    assert cid.startswith("ESPN+")
    assert "NBA" in cid or "Lakers" in cid


def test_build_channel_id():
    entry = PlaylistEntry(name="Test Channel!", stream_url="http://example.com")
    cid = _build_channel_id(entry, prefix="ESPN+")
    assert "Test_Channel_" in cid


def test_format_xmltv_time():
    formatted = _format_xmltv_time("2024-01-15T20:00:00+00:00")
    assert "20240115" in formatted
    assert "-0" in formatted or "+0" in formatted


def test_empty_matches():
    xml = generate_xmltv([])
    assert "<tv" in xml
    assert "<channel" not in xml


def test_multiple_channels_each_have_three():
    e1 = make_entry("Game 1")
    m1 = make_metadata("Game 1", "2024-01-15T18:00:00+00:00", "2024-01-15T20:00:00+00:00")
    e2 = make_entry("Game 2")
    m2 = make_metadata("Game 2", "2024-01-15T22:30:00+00:00", "2024-01-16T00:30:00+00:00")
    xml = generate_xmltv([(e1, m1), (e2, m2)])
    root = etree.fromstring(xml.encode("utf-8"))
    assert len(root.findall("channel")) == 2
    assert len(root.findall("programme")) == 6


def test_pt_offset_in_all_programmes():
    entry = make_entry("NBA: Lakers vs Celtics")
    metadata = make_metadata(
        "Lakers vs Celtics",
        "2024-01-15T20:00:00+00:00",
        "2024-01-15T22:00:00+00:00",
    )
    xml = generate_xmltv([(entry, metadata)])
    root = etree.fromstring(xml.encode("utf-8"))
    for prog in root.findall("programme"):
        s = prog.get("start")
        e = prog.get("stop")
        assert "-0" in s or "+0" in s
        assert "-0" in e or "+0" in e


def test_programmes_use_stop_attribute_not_end():
    entry = make_entry("NBA: Lakers vs Celtics")
    metadata = make_metadata(
        "Lakers vs Celtics",
        "2024-01-15T20:00:00+00:00",
        "2024-01-15T22:00:00+00:00",
    )
    xml = generate_xmltv([(entry, metadata)])
    root = etree.fromstring(xml.encode("utf-8"))
    progs = root.findall("programme")
    assert len(progs) == 3
    for prog in progs:
        assert prog.get("start") is not None
        assert prog.get("stop") is not None
        assert prog.get("end") is None
