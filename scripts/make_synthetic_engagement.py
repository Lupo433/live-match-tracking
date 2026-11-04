"""Write a SYNTHETIC engagement CSV for a match (fixed seed, no real data).

Usage:
    python scripts/make_synthetic_engagement.py [match_id] [--seed 42]

Output: data/synthetic/engagement_<match_id>.csv (long format: timestamp, metric, value).
"""

from __future__ import annotations

import argparse
from pathlib import Path

from livematch.catalog import default_catalog
from livematch.engagement.marketing import synthetic_engagement
from livematch.engagement.synthetic import SYNTHETIC_NOTICE
from livematch.metrics.engine import MetricsEngine
from livematch.session import CheckpointStore

OUT_DIR = Path(__file__).resolve().parents[1] / "data" / "synthetic"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("match_id", nargs="?", default="sample_game_1")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    src = default_catalog().get(args.match_id)
    store = CheckpointStore(src, MetricsEngine.for_source)
    store.run()
    excitement = store.final_state()["excitement"].series
    df, k = synthetic_engagement(src, excitement, seed=args.seed)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"engagement_{args.match_id}.csv"
    with out.open("w") as fh:
        fh.write(f"# {SYNTHETIC_NOTICE}\n")
        fh.write(
            f"# match={args.match_id} seed={args.seed} kickoff(UTC)="
            + ";".join(f"P{p}={w.tz_convert('UTC').isoformat()}" for p, w in k.wall.items())
            + f" delay_s={k.offset_s}\n"
        )
        df.to_csv(fh, index=False)
    print(f"{len(df)} rows written to {out}")


if __name__ == "__main__":
    main()
