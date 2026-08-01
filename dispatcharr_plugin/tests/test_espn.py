from dispatcharr_plugin.espn import _parse_airing


def make_airing(**overrides):
    airing = {
        "id": "abc-123",
        "name": "Sacramento Republic FC vs. Sporting Club Jacksonville",
        "shortName": "Sacramento FC vs. Sporting JAX",
        "subtitle": "ESPN+ • USL Championship",
        "description": None,
        "startDateTime": "2026-08-02T03:00:00Z",
        "endDateTime": "2026-08-02T05:00:00Z",
        "duration": 7200,
        "sport": {"name": "Soccer", "abbreviation": "soc"},
        "league": {"name": "USL Championship", "abbreviation": "usl"},
        "category": {"name": "Soccer"},
        "subcategory": {"name": "USL Championship"},
        "program": {"isStudio": False},
        "image": {"url": ""},
    }
    airing.update(overrides)
    return airing


def test_parse_airing_subtitle_and_description():
    parsed = _parse_airing(make_airing())
    assert parsed is not None
    assert parsed["subtitle"] == "ESPN+ • USL Championship"
    assert parsed["description"] == ""


def test_parse_airing_description_present():
    parsed = _parse_airing(make_airing(description="A soccer match"))
    assert parsed["description"] == "A soccer match"


def test_parse_airing_missing_subtitle_and_description():
    parsed = _parse_airing(
        make_airing(subtitle=None, description=None)
    )
    assert parsed is not None
    assert parsed["subtitle"] == ""
    assert parsed["description"] == ""


def test_parse_airing_no_name_returns_none():
    assert _parse_airing(make_airing(name="")) is None
