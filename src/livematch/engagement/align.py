"""Alignment of wall-clock engagement series to the match clock."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class KickoffTimes:
    """Wall-clock kick-off of each period and the data timestamp where it starts.

    ``offset_s`` is the delay between the stadium and the audience (broadcast /
    streaming latency): engagement at wall time ``w`` reacts to what happened at
    ``w - offset_s``. It is subtracted during alignment.
    """

    wall: dict[int, pd.Timestamp]  # period -> wall-clock kick-off
    data_start: dict[int, float]  # period -> match-data timestamp (s) of the kick-off
    period_end: dict[int, float]  # period -> last match-data timestamp (s) of the period
    offset_s: float = 0.0


def to_match_seconds(ts: pd.Series, k: KickoffTimes) -> pd.Series:
    """Map wall-clock timestamps to match-data seconds (NaN outside the periods)."""
    ts = pd.to_datetime(ts, utc=True)
    out = pd.Series(np.nan, index=ts.index, dtype=float)
    for period, wall in sorted(k.wall.items()):
        wall = (
            pd.Timestamp(wall).tz_convert("UTC")
            if pd.Timestamp(wall).tzinfo
            else (pd.Timestamp(wall).tz_localize("UTC"))
        )
        elapsed = (ts - wall).dt.total_seconds() - k.offset_s
        t = k.data_start[period] + elapsed
        inside = (elapsed >= 0) & (t <= k.period_end[period])
        out[inside] = t[inside]
    return out


def align(df: pd.DataFrame, k: KickoffTimes, metric: str, step_s: float = 1.0) -> pd.Series:
    """One metric resampled on a regular match-time grid (mean per bucket).

    Returns a Series indexed by match-data seconds (bucket start).
    """
    sub = df[df["metric"] == metric]
    t = to_match_seconds(sub["timestamp"], k)
    ok = t.notna()
    bucket = (t[ok] // step_s) * step_s
    return sub.loc[ok, "value"].groupby(bucket.values).mean().sort_index()
