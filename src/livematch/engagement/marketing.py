"""Marketing view of a match: excitement index vs (SYNTHETIC) engagement."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from livematch.engagement.align import KickoffTimes, align
from livematch.engagement.analysis import event_study, lagged_correlation
from livematch.engagement.synthetic import DELAY_S, STEP_S, SYNTHETIC_NOTICE, generate
from livematch.schema import Event
from livematch.sources.base import DataSource

PRIMARY_METRIC = "synthetic_social_posts_per_min"


def period_bounds(source: DataSource) -> dict[int, tuple[float, float]]:
    """period -> (start s, end s) in match-data seconds (= frame index / fps)."""
    fps = source.info.fps
    starts = sorted(source.info.period_starts.items())
    out = {}
    for k, (p, f0) in enumerate(starts):
        f1 = starts[k + 1][1] - 1 if k + 1 < len(starts) else len(source) - 1
        out[p] = (f0 / fps, f1 / fps)
    return out


def match_moments(source: DataSource) -> list[tuple[float, str, Event]]:
    fps = source.info.fps
    out = []
    for e in source.events:
        if e.event_type == "SHOT":
            out.append((e.effective_frame / fps, "goal" if e.is_goal else "shot", e))
    return out


def synthetic_engagement(source: DataSource, excitement: list[int], seed: int = 42):
    bounds = period_bounds(source)
    moments = [(t, kind) for t, kind, _ in match_moments(source)]
    df, walls = generate(bounds, excitement, moments, seed=seed)
    k = KickoffTimes(
        wall=walls,
        data_start={p: b[0] for p, b in bounds.items()},
        period_end={p: b[1] for p, b in bounds.items()},
        offset_s=DELAY_S,
    )
    return df, k


def marketing_payload(source: DataSource, excitement: list[int]) -> dict[str, Any]:
    df, k = synthetic_engagement(source, excitement)
    eng = align(df, k, PRIMARY_METRIC, step_s=STEP_S)
    exc = pd.Series(np.asarray(excitement, float), index=np.arange(len(excitement), dtype=float))
    exc10 = exc.groupby((exc.index // STEP_S) * STEP_S).mean()
    corr = lagged_correlation(exc10, eng, max_lag_s=180, step_s=STEP_S)
    best = corr.loc[corr["r"].idxmax()] if not corr.empty and corr["r"].notna().any() else None
    fps = source.info.fps
    labels = []
    for t, kind, e in match_moments(source):
        team = e.team.value if e.team else None
        who = (e.player_id or "")[1:]
        labels.append((t, f"{'Gol' if kind == 'goal' else 'Tiro'} #{who}", team))
    moments = event_study(eng, labels)
    return {
        "synthetic": True,
        "notice": SYNTHETIC_NOTICE,
        "metric": PRIMARY_METRIC,
        "step_s": STEP_S,
        "fps": fps,
        "excitement": [int(v) for v in excitement],
        "engagement": {
            "t": [float(t) for t in eng.index],
            "v": [round(float(v), 1) for v in eng.to_numpy()],
        },
        "moments": [
            {
                "t": round(m.t, 1),
                "frame": int(m.t * fps),
                "label": m.label,
                "team": m.team,
                "baseline": round(m.baseline, 1),
                "after": round(m.after, 1),
                "lift": round(m.lift, 3),
            }
            for m in moments
        ],
        "correlation": None
        if best is None
        else {"lag_s": float(best["lag_s"]), "r": round(float(best["r"]), 3)},
    }
