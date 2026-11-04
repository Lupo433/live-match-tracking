import math

import numpy as np
import pytest

from livematch.analytics.geometry import attacking_xy, shot_angle, shot_distance
from livematch.analytics.models import get_models
from livematch.analytics.passes import pass_network
from livematch.analytics.xg import fit_xg
from livematch.analytics.xt import credited_values, extract_moves, fit_xt, player_xt
from livematch.metrics.threat import ThreatTracker
from livematch.schema import Event, Team

H = Team.HOME


def ev(kind, x, y, ex=None, ey=None, sub="", pid="H1", to=None, t=0.0, team=H):
    return Event(kind, sub, team, pid, 1, t, int(t * 25), x, y, ex, ey, to_player_id=to)


def test_geometry():
    assert shot_distance(94.0, 34.0) == pytest.approx(11.0)
    # the goal mouth is seen under a wider angle from closer and more central spots
    assert shot_angle(94, 34) > shot_angle(80, 34) > 0
    assert shot_angle(94, 34) > shot_angle(94, 10)
    assert shot_angle(94, 34) == pytest.approx(2 * math.atan(3.66 / 11), rel=1e-6)
    assert attacking_xy(10.0, 20.0, Team.AWAY) == (95.0, 48.0)


def test_xt_value_iteration_known_answer():
    # 2 x 1 grid: cell A = left half, cell B = right half
    events = [ev("SHOT", 80, 34, sub="ON TARGET-GOAL", t=1)]
    events += [ev("SHOT", 85, 34, sub="OFF TARGET", t=2)]
    events += [ev("PASS", 20, 34, 70, 34, t=3 + k) for k in range(4)]
    m = fit_xt(events, nx=2, ny=1)
    # B: only shots, half of them goals -> 0.5; A: only moves, all reach B -> 0.5
    assert m.grid[0, 1] == pytest.approx(0.5)
    assert m.grid[0, 0] == pytest.approx(0.5)
    events += [ev("BALL LOST", 30, 34, t=10 + k) for k in range(4)]  # failed moves in A
    m = fit_xt(events, nx=2, ny=1)
    assert m.grid[0, 0] == pytest.approx(0.25)
    assert m.n_shots == 2 and m.n_goals == 1 and m.n_moves == 8


def test_carry_detection_and_credit():
    events = [
        ev("PASS", 30, 34, 60, 34, pid="H4", to="H8", t=1),
        ev("PASS", 75, 34, 90, 34, pid="H8", to="H9", t=3),  # H8 carried 60 -> 75
    ]
    kinds = [mv.kind for mv in extract_moves(events)]
    assert kinds == ["pass", "carry", "pass"]
    model = get_models().xt
    credits = credited_values(model, events)
    assert [c[1] for c in credits] == ["H4", "H8", "H8"]
    totals = player_xt(model, events)
    assert totals["H8"] == pytest.approx(
        model.added((60, 34), (75, 34)) + model.added((75, 34), (90, 34))
    )


def test_shipped_xt_grid_grows_towards_goal():
    m = get_models().xt
    assert m.value(100, 34) > m.value(70, 34) > m.value(20, 34)


def test_xg_fit_monotonic_and_honest():
    rng = np.random.default_rng(0)
    events = []
    for k in range(200):
        x = rng.uniform(70, 103)
        y = rng.uniform(15, 53)
        p = 1 / (1 + math.exp(-(-3 + 3.0 * shot_angle(x, y))))
        goal = rng.random() < p
        events.append(ev("SHOT", x, y, sub="ON TARGET-GOAL" if goal else "OFF TARGET", t=k))
    m = fit_xg(events, n_boot=100)
    assert m.n_shots == 200 and m.label == "modello dimostrativo"
    assert m.predict(97, 34) > m.predict(80, 34)  # closer => higher
    assert m.predict(95, 34) > m.predict(95, 12)  # more central => higher
    lo, hi = m.ci95["angle_rad"]
    assert lo < m.coef[1] < hi


def test_shipped_xg_model_is_labelled_and_sane():
    m = get_models().xg
    assert m.label == "modello dimostrativo" and 0 < m.n_shots < 100
    assert m.predict(97, 34) > m.predict(85, 34) > m.predict(75, 20)
    assert 0 < m.predict(94, 34) < 1


def test_pass_network_counts():
    events = [ev("PASS", 30, 30, 40, 40, pid="H4", to="H8", t=k) for k in range(3)]
    events += [ev("PASS", 40, 40, 30, 30, pid="H8", to="H4", t=10)]
    events += [ev("PASS", 40, 40, 60, 10, pid="H8", to="H9", t=11)]
    net = pass_network(events, H, min_passes=3)
    edge = net["edges"][0]
    assert {edge["a"], edge["b"]} == {"H4", "H8"} and edge["count"] == 4
    assert len(net["edges"]) == 1  # H8-H9 below threshold
    nodes = {n["player"]: n for n in net["nodes"]}
    assert nodes["H4"]["x"] == pytest.approx(30.0) and nodes["H8"]["n"] == 2
    assert pass_network(events, H, until_frame=0)["nodes"][0]["n"] == 1


def test_threat_tracker_incremental_equals_batch():
    events = [
        ev("PASS", 30, 34, 60, 34, pid="H4", to="H8", t=1),
        ev("PASS", 75, 34, 90, 34, pid="H8", to="H9", t=3),
        ev("SHOT", 95, 34, pid="H9", sub="ON TARGET-GOAL", t=4),
    ]
    tr = ThreatTracker()
    for e in events:  # one at a time, as the replay does
        tr.update([e])
    batch = player_xt(get_models().xt, events)
    assert tr.player_xt == pytest.approx(batch)
    assert tr.xg["home"] == pytest.approx(get_models().xg.predict(95, 34))
    assert tr.xt["away"] == 0.0
