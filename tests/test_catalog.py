from livematch.catalog import default_catalog


def test_catalog_has_sample_and_synthetic(tmp_path):
    from .conftest import ROOT

    cat = default_catalog(ROOT / "data")
    ids = [e.match_id for e in cat.list()]
    assert "synthetic" in ids and "sample_game_1" in ids
    src = cat.get("sample_game_1")
    assert cat.get("sample_game_1") is src  # cached


def test_catalog_without_data_falls_back_to_synthetic(tmp_path):
    cat = default_catalog(tmp_path)
    assert [e.match_id for e in cat.list()] == ["synthetic"]
    assert cat.default_id == "synthetic"
