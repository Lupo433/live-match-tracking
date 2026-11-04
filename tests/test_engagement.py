import numpy as np
import pandas as pd
import pytest

from livematch.engagement.align import KickoffTimes, align, to_match_seconds
from livematch.engagement.analysis import average_profile, event_study, lagged_correlation
from livematch.engagement.schema import read_csv, validate
from livematch.engagement.synthetic import METRICS, SYNTHETIC_NOTICE, generate

from .conftest import ROOT

KO1 = pd.Timestamp("2030-01-01 20:00", tz="UTC")
KO2 = pd.Timestamp("2030-01-01 21:00", tz="UTC")
K = KickoffTimes(
    wall={1: KO1, 2: KO2},
    data_start={1: 0.0, 2: 2700.0},
    period_end={1: 2699.0, 2: 5399.0},
    offset_s=30.0,
)


def test_alignment_with_offset_and_half_time():
    ts = pd.Series(
        [
            KO1 - pd.Timedelta(seconds=10),  # before kick-off
            KO1 + pd.Timedelta(seconds=30),  # = data 0 s after the 30 s delay
            KO1 + pd.Timedelta(seconds=130),  # data 100 s
            KO1 + pd.Timedelta(minutes=50),  # half-time break
            KO2 + pd.Timedelta(seconds=90),  # data 2700 + 60 s
        ]
    )
    t = to_match_seconds(ts, K)
    assert np.isnan(t[0]) and np.isnan(t[3])
    assert t[1] == pytest.approx(0.0) and t[2] == pytest.approx(100.0)
    assert t[4] == pytest.approx(2760.0)


def test_align_resamples_one_metric():
    rows = [(KO1 + pd.Timedelta(seconds=30 + s), "m", float(s)) for s in range(0, 40)]
    rows += [(KO1 + pd.Timedelta(seconds=40), "other", 999.0)]
    df = validate(pd.DataFrame(rows, columns=["timestamp", "metric", "value"]))
    s = align(df, K, "m", step_s=10)
    assert list(s.index) == [0.0, 10.0, 20.0, 30.0]
    assert s.iloc[0] == pytest.approx(4.5)  # mean of 0..9


def test_event_study_lift_known_answer():
    idx = np.arange(0, 1200, 10.0)
    vals = np.where(idx >= 600, 150.0, 100.0)
    s = pd.Series(vals, index=idx)
    (m,) = event_study(s, [(600.0, "Gol", "home")], before_s=300, after_s=180, gap_s=30)
    assert m.baseline == pytest.approx(100.0) and m.after == pytest.approx(150.0)
    assert m.lift == pytest.approx(0.5)
    prof = average_profile(s, [600.0], window_s=60, step_s=30)
    assert prof.loc[-60] == 100.0 and prof.loc[60] == 150.0


def test_lagged_correlation_finds_the_delay():
    rng = np.random.default_rng(1)
    x = pd.Series(rng.normal(size=300), index=np.arange(300) * 10.0)
    y = pd.Series(np.roll(x.to_numpy(), 3), index=x.index)  # y(t) = x(t - 30 s)
    c = lagged_correlation(x, y, max_lag_s=60, step_s=10)
    best = c.loc[c["r"].idxmax()]
    assert best["lag_s"] == 30.0 and best["r"] > 0.95


def test_synthetic_generator_is_deterministic_and_peaks_after_goals():
    bounds = {1: (0.0, 1800.0)}
    exc = [20] * 1801
    a, walls = generate(bounds, exc, [(600.0, "goal")], seed=7)
    b, _ = generate(bounds, exc, [(600.0, "goal")], seed=7)
    pd.testing.assert_frame_equal(a, b)
    assert set(a["metric"]) == set(METRICS) and (a["value"] >= 0).all()
    k = KickoffTimes(walls, {1: 0.0}, {1: 1800.0}, offset_s=40.0)
    s = align(a, k, "synthetic_social_posts_per_min", step_s=10)
    (m,) = event_study(s, [(600.0, "Gol", "home")])
    assert m.lift > 1.0  # strong synthetic peak after the goal


def test_committed_sample_csv_is_declared_synthetic():
    path = ROOT / "data" / "synthetic" / "engagement_sample_game_1.csv"
    assert path.read_text().splitlines()[0] == f"# {SYNTHETIC_NOTICE}"
    df = read_csv(path)
    assert len(df) > 100 and df["metric"].str.startswith("synthetic_").all()
