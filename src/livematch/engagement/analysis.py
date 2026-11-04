"""Event study and correlation between excitement and engagement."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class Moment:
    t: float  # match-data seconds
    label: str
    team: str | None
    baseline: float
    after: float

    @property
    def lift(self) -> float:
        return self.after / self.baseline - 1.0 if self.baseline > 0 else float("nan")


def event_study(
    series: pd.Series,
    moments: list[tuple[float, str, str | None]],
    before_s: float = 300.0,
    after_s: float = 180.0,
    gap_s: float = 30.0,
) -> list[Moment]:
    """Engagement lift around match moments.

    baseline = mean of ``series`` in [t - before_s, t - gap_s);
    after    = mean in [t, t + after_s).
    The small gap avoids counting the build-up (e.g. the attack before a goal).
    """
    idx = series.index.to_numpy(dtype=float)
    vals = series.to_numpy(dtype=float)
    out = []
    for t, label, team in moments:
        b = vals[(idx >= t - before_s) & (idx < t - gap_s)]
        a = vals[(idx >= t) & (idx < t + after_s)]
        if len(b) == 0 or len(a) == 0:
            continue
        out.append(Moment(t, label, team, float(np.mean(b)), float(np.mean(a))))
    return sorted(out, key=lambda m: -m.lift)


def average_profile(
    series: pd.Series, times: list[float], window_s: float = 300.0, step_s: float = 30.0
) -> pd.Series:
    """Mean engagement relative to the event time (index = seconds from the event)."""
    rel = np.arange(-window_s, window_s + step_s, step_s)
    rows = []
    for t in times:
        rows.append(
            np.interp(
                t + rel,
                series.index.to_numpy(float),
                series.to_numpy(float),
                left=np.nan,
                right=np.nan,
            )
        )
    return pd.Series(np.nanmean(np.array(rows), axis=0), index=rel)


def lagged_correlation(
    x: pd.Series, y: pd.Series, max_lag_s: float = 180.0, step_s: float = 10.0
) -> pd.DataFrame:
    """Pearson correlation between x(t) and y(t + lag) for lag in [0, max_lag_s].

    Both series must share the same regular index (match seconds).
    """
    df = pd.DataFrame({"x": x, "y": y}).dropna()
    if df.empty:
        return pd.DataFrame(columns=["lag_s", "r"])
    dt = float(np.median(np.diff(df.index.to_numpy(float)))) if len(df) > 1 else step_s
    rows = []
    xs, ys = df["x"].to_numpy(float), df["y"].to_numpy(float)
    for lag in np.arange(0, max_lag_s + step_s, step_s):
        shift = int(round(lag / dt))
        if len(xs) - shift < 3:
            rows.append((float(lag), float("nan")))
            continue
        a, b = xs[: len(xs) - shift], ys[shift:]
        if a.std() == 0 or b.std() == 0:
            rows.append((float(lag), float("nan")))
            continue
        rows.append((float(lag), float(np.corrcoef(a, b)[0, 1])))
    return pd.DataFrame(rows, columns=["lag_s", "r"])
