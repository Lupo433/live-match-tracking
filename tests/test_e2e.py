"""End-to-end on the committed Metrica sample: loader -> replay -> metrics -> JSON."""

import json

import numpy as np
import pytest

from livematch.metrics.engine import MetricsEngine
from livematch.session import MatchSession
from livematch.sources.metrica import load_metrica

from .conftest import SAMPLE_DIR
from .test_replay import FakeClock


@pytest.fixture(scope="module")
def final_stats():
    src = load_metrica(SAMPLE_DIR / "Sample_Game_1", "sample")
    clk = FakeClock()
    s = MatchSession(src, MetricsEngine.for_source, clock=clk)
    s.replay.set_speed(10.0)
    s.replay.play()
    msg = None
    while True:
        clk.advance(0.04)
        msg = s.tick(budget_s=1.0, force_stats=True)
        json.dumps(msg)
        if not msg["playing"]:
            break
    assert s.cursor == len(src)
    return src, msg["st"]


def test_distances_are_plausible(final_stats):
    src, st = final_stats
    rows = st["players"]
    starters = [r for r in rows if r[6]]
    assert len(starters) == 22
    dists = np.array([r[1] for r in starters])
    # two minutes of football: outfield players cover ~150-350 m
    outfield = [r[1] for r in starters if not src.players[r[0]].is_goalkeeper]
    assert 120 < np.median(outfield) < 400
    assert dists.max() < 600
    assert all(r[3] < 12.5 for r in rows)  # no superhuman speeds


def test_team_metrics_are_consistent(final_stats):
    _, st = final_stats
    assert st["poss"]["home"] + st["poss"]["away"] == pytest.approx(1.0)
    assert 0.1 < st["pc"]["home"] < 0.9
    for team in ("home", "away"):
        t = st["teams"][team]
        assert 15 < t["avg_width"] < 68
        assert 15 < t["avg_length"] < 70
        assert 5 < t["avg_line"] < 60
    assert st["ball"]["vmax"] > 10
    assert st["teams"]["home"]["passes"] + st["teams"]["away"]["passes"] > 10
