import numpy as np
import pytest

from livematch.metrics.engine import MetricsEngine
from livematch.metrics.excitement import WEIGHTS, ExcitementTracker, index_from_raw
from livematch.schema import Event, Frame, Player, Team

FPS = 25.0


def test_weights_and_scale():
    assert sum(WEIGHTS.values()) == pytest.approx(1.0)
    assert index_from_raw(0.0) == 0 and index_from_raw(0.75) == 100 and index_from_raw(2) == 100
    assert index_from_raw(0.375) == 50


def _players():
    out = []
    for t_i, team in enumerate((Team.HOME, Team.AWAY)):
        for k in range(11):
            out.append(
                Player(
                    t_i * 11 + k, f"{team.value[0].upper()}{k}", team, k + 1, is_goalkeeper=(k == 0)
                )
            )
    return out


def _run(scenario: str, seconds: int = 20) -> list[int]:
    """Two synthetic situations with an obvious answer."""
    rng = np.random.default_rng(0)
    players = _players()
    events = []
    base = np.zeros((22, 2))
    if scenario == "goal":
        # home attack in the box, shot + goal at t = 5 s
        base[:11] = [[30, 34]] + [[80 + rng.uniform(0, 15), rng.uniform(20, 48)] for _ in range(10)]
        base[11:] = [[103, 34]] + [
            [85 + rng.uniform(0, 15), rng.uniform(20, 48)] for _ in range(10)
        ]
        events = [Event("SHOT", "ON TARGET-GOAL", Team.HOME, "H9", 1, 5.0, 125, 96.0, 34.0)]
    else:
        # slow possession around the centre circle
        base[:11] = [[5, 34]] + [[35 + rng.uniform(0, 15), rng.uniform(10, 58)] for _ in range(10)]
        base[11:] = [[100, 34]] + [
            [55 + rng.uniform(0, 15), rng.uniform(10, 58)] for _ in range(10)
        ]
    eng = MetricsEngine(players, FPS, events)
    for k in range(int(seconds * FPS)):
        t = k / FPS
        pos = base + np.array([np.sin(t), np.cos(t)]) * 0.4  # gentle jogging
        if scenario == "goal":
            ball = np.array(
                [88 + 15 * min(1.0, t / 6), 34 + 3 * np.sin(3 * t)]
            )  # fast, towards goal
        else:
            ball = np.array([52.5 + 2 * np.sin(0.3 * t), 34.0])  # slow, central
        eng.update(Frame(k, t, 1, pos, ball))
    return eng.excitement.series


def test_goal_is_more_exciting_than_midfield_possession():
    goal = _run("goal")
    calm = _run("calm")
    assert len(goal) == len(calm) == 20
    assert max(goal[5:12]) >= 60  # around the goal
    assert max(calm) <= 30
    assert np.mean(goal) > 2 * np.mean(calm)


def test_threat_decays_after_the_goal():
    tr = ExcitementTracker(FPS)
    tr.add_shot(0.0, 0.4, True)
    vals = []
    for k in range(int(120 * FPS)):
        v = tr.update(k / FPS, np.array([np.nan, np.nan]), 0.0, 0.0, None)
        if v is not None:
            vals.append(v)
    assert vals[3] > vals[30] > vals[100]
    assert vals[-1] <= 5
