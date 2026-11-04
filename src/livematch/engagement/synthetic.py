"""SYNTHETIC engagement generator (fixed seed). NOT real data of any company.

Model per metric, sampled every 10 s of wall-clock time:

    value(w) = level * (1 + trend) * (1 + 0.25 * excitement(w - delay) / 100)
               + sum_events amplitude * exp(-(w - delay - t_event) / tau)   (after the event)
               + noise (Gaussian, 6% of the level)

with a broadcast/streaming delay of 40 s. Goals produce the largest peaks,
shots smaller ones. Half-time shows a plateau at a lower level.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

SYNTHETIC_NOTICE = "DATI SINTETICI DIMOSTRATIVI - generati con seed fisso, nessun dato reale"
METRICS = {
    # name: (level, goal amplitude, shot amplitude, tau seconds)
    "synthetic_social_posts_per_min": (400.0, 2600.0, 500.0, 150.0),
    "synthetic_app_active_users": (12000.0, 9000.0, 1500.0, 300.0),
}
DEFAULT_KICKOFF = pd.Timestamp("2030-03-02 20:45", tz="Europe/Rome")
HALF_TIME_S = 15 * 60
DELAY_S = 40.0
STEP_S = 10.0


def generate(
    match_duration_s: dict[int, tuple[float, float]],
    excitement: list[int] | np.ndarray,
    moments: list[tuple[float, str]],
    seed: int = 42,
    kickoff: pd.Timestamp = DEFAULT_KICKOFF,
) -> tuple[pd.DataFrame, dict[int, pd.Timestamp]]:
    """Generate a long-format engagement frame for one match.

    Args:
        match_duration_s: period -> (data start s, data end s).
        excitement: per-second excitement index (index = match-data second).
        moments: (match-data second, kind) with kind in {"goal", "shot"}.

    Returns the frame and the wall-clock kick-off of each period.
    """
    rng = np.random.default_rng(seed)
    exc = np.asarray(excitement, dtype=float)
    walls: dict[int, pd.Timestamp] = {}
    wall = kickoff
    rows = []
    periods = sorted(match_duration_s)
    first_wall = kickoff - pd.Timedelta(minutes=10)
    last_wall = kickoff
    # map data time -> wall time per period
    for p in periods:
        start, end = match_duration_s[p]
        walls[p] = wall
        wall = wall + pd.Timedelta(seconds=end - start) + pd.Timedelta(seconds=HALF_TIME_S)
        last_wall = walls[p] + pd.Timedelta(seconds=end - start)
    grid = pd.date_range(first_wall, last_wall + pd.Timedelta(minutes=10), freq=f"{int(STEP_S)}s")

    def data_time(w: pd.Timestamp) -> float | None:
        for p in periods:
            start, end = match_duration_s[p]
            el = (w - walls[p]).total_seconds() - DELAY_S
            if 0 <= el <= end - start:
                return start + el
        return None

    total = (grid[-1] - grid[0]).total_seconds()
    for name, (level, amp_goal, amp_shot, tau) in METRICS.items():
        for w in grid:
            trend = 0.15 * (w - grid[0]).total_seconds() / total
            t = data_time(w)
            ex = exc[int(t)] if t is not None and 0 <= int(t) < len(exc) else 0.0
            in_play = t is not None
            base = level * (1 + trend) * (1 + 0.25 * ex / 100.0) * (1.0 if in_play else 0.8)
            peak = 0.0
            if in_play:
                for tm, kind in moments:
                    dt = t - tm
                    if dt >= 0:
                        amp = amp_goal if kind == "goal" else amp_shot
                        peak += amp * np.exp(-dt / tau)
            value = max(0.0, base + peak + rng.normal(0, 0.06 * level))
            rows.append((w, name, round(value, 1)))
    df = pd.DataFrame(rows, columns=["timestamp", "metric", "value"])
    df["timestamp"] = df["timestamp"].dt.tz_convert("UTC")
    return df, walls
