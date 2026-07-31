from dispatcharr_plugin.normalize import normalize_title


def test_lowercase():
    assert normalize_title("ESPN+ NFL Football") == "nfl football"


def test_remove_punctuation():
    result = normalize_title("Match: Team A vs Team B!")
    assert ":" not in result
    assert "!" not in result


def test_normalize_vs():
    result = normalize_title("Team A vs Team B")
    assert " vs " in result
    assert normalize_title("Team A vs Team B") == normalize_title("Team A v Team B")


def test_normalize_at():
    assert normalize_title("Team A @ Team B") == normalize_title("Team A vs Team B")
    assert normalize_title("Team A at Team B") == normalize_title("Team A vs Team B")


def test_remove_live():
    assert "live" not in normalize_title("LIVE: ESPN+ Game")
    assert "live" not in normalize_title("Game LIVE HD")


def test_remove_hd():
    assert "hd" not in normalize_title("Game HD")


def test_remove_espn_plus():
    result = normalize_title("ESPN+ College Basketball")
    assert "espn+" not in result


def test_remove_duplicate_spaces():
    result = normalize_title("ESPN+   NFL   Football")
    assert "  " not in result


def test_empty_string():
    assert normalize_title("") == ""


def test_none_input():
    assert normalize_title(None) == ""


def test_complex_title():
    result = normalize_title("LIVE: ESPN+ MLB Baseball - Yankees vs Red Sox HD")
    assert "live" not in result
    assert "espn+" not in result
    assert "hd" not in result
    assert " vs " in result
    assert "yankees" in result
    assert "red sox" in result
