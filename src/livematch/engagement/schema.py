"""Generic long-format schema for engagement time series.

One row per (timestamp, metric):

* ``timestamp`` timezone-aware wall-clock time (pandas ``Timestamp``)
* ``metric``    free-text metric name (e.g. ``"synthetic_social_posts"``)
* ``value``     float
"""

from __future__ import annotations

import pandas as pd

COLUMNS = ("timestamp", "metric", "value")


def validate(df: pd.DataFrame) -> pd.DataFrame:
    """Check columns/types and return a clean, sorted copy."""
    missing = set(COLUMNS) - set(df.columns)
    if missing:
        raise ValueError(f"missing columns: {sorted(missing)}")
    out = df.loc[:, list(COLUMNS)].copy()
    out["timestamp"] = pd.to_datetime(out["timestamp"], utc=True)
    out["metric"] = out["metric"].astype(str)
    out["value"] = pd.to_numeric(out["value"], errors="coerce")
    return out.dropna(subset=["value"]).sort_values(["metric", "timestamp"]).reset_index(drop=True)


def read_csv(path) -> pd.DataFrame:
    """Read a long-format CSV (lines starting with ``#`` are comments)."""
    return validate(pd.read_csv(path, comment="#"))
