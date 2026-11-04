import os
import shutil

import numpy as np
import pytest

from livematch import cache
from livematch.metrics.engine import MetricsEngine
from livematch.session import CheckpointStore
from livematch.sources.metrica import load_metrica_cached

from .conftest import SAMPLE_DIR


@pytest.fixture
def game_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("LIVEMATCH_CACHE_DIR", str(tmp_path / "cache"))
    d = tmp_path / "Sample_Game_1"
    shutil.copytree(SAMPLE_DIR / "Sample_Game_1", d)
    return d


def _files(kind):
    return sorted((cache.cache_root() / kind).glob("*"))


def test_source_cache_hit_returns_identical_data(game_dir):
    a = load_metrica_cached(game_dir, "g")
    assert len(_files("sources")) == 1
    b = load_metrica_cached(game_dir, "g")
    assert a.cache_key == b.cache_key
    assert np.array_equal(a.positions, b.positions, equal_nan=True)
    assert np.array_equal(a.ball, b.ball, equal_nan=True)
    assert a.players == b.players and a.events == b.events and a.info == b.info


def test_source_cache_is_invalidated_when_csv_changes(game_dir):
    a = load_metrica_cached(game_dir, "g")
    ev = next(game_dir.glob("*Events*"))
    st = ev.stat()
    os.utime(ev, ns=(st.st_atime_ns, st.st_mtime_ns + 10**9))
    b = load_metrica_cached(game_dir, "g")
    assert a.cache_key != b.cache_key
    assert len(_files("sources")) == 1  # the stale file was replaced


def test_corrupted_source_cache_is_rebuilt(game_dir):
    a = load_metrica_cached(game_dir, "g")
    path = _files("sources")[0]
    path.write_bytes(b"not an npz")
    b = load_metrica_cached(game_dir, "g")
    assert np.array_equal(a.positions, b.positions, equal_nan=True)
    assert cache.load_source("g", b.cache_key) is not None  # rewritten


def test_checkpoint_cache_hit_and_corruption(game_dir):
    src = load_metrica_cached(game_dir, "g")
    first = CheckpointStore(src, MetricsEngine.for_source, every=500)
    first.run()
    assert not first.loaded_from_cache and len(_files("checkpoints")) == 1
    second = CheckpointStore(src, MetricsEngine.for_source, every=500)
    second.run()
    assert second.loaded_from_cache and second.done
    assert second.final_snapshot == first.final_snapshot
    k, state = second.best(1700)
    assert k == 1500
    eng = MetricsEngine.for_source(src)
    eng.restore(state)
    for f in src.frames(1500, len(src)):
        eng.update(f)
    assert eng.snapshot() == first.final_snapshot  # restored state continues correctly
    _files("checkpoints")[0].write_bytes(b"garbage")
    third = CheckpointStore(src, MetricsEngine.for_source, every=500)
    third.run()
    assert not third.loaded_from_cache and third.final_snapshot == first.final_snapshot


def test_cache_can_be_disabled(game_dir, monkeypatch):
    monkeypatch.setenv("LIVEMATCH_CACHE", "0")
    load_metrica_cached(game_dir, "g")
    assert _files("sources") == []
