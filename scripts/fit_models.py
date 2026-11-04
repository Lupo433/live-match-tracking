"""Fit the demonstrative xT grid and xG model on the downloaded Metrica matches.

Usage:
    python scripts/download_data.py   # once
    python scripts/fit_models.py

Writes src/livematch/analytics/models.json (committed, a few KB).
"""

from __future__ import annotations

import json

from livematch.analytics.models import MODELS_PATH
from livematch.analytics.xg import fit_xg
from livematch.analytics.xt import fit_xt
from livematch.catalog import default_catalog


def main() -> None:
    catalog = default_catalog()
    train = [m for m in ("metrica_game_1", "metrica_game_2") if m in catalog]
    if not train:
        raise SystemExit("Run scripts/download_data.py first (full Metrica matches needed).")
    events = [e for mid in train for e in catalog.get(mid).events]
    xt = fit_xt(events)
    xg = fit_xg(events)
    out = {
        "meta": {
            "trained_on": train,
            "warning": "Demonstrative models fitted on 2 public matches: not predictive.",
        },
        "xt": xt.to_dict(),
        "xg": xg.to_dict(),
    }
    MODELS_PATH.write_text(json.dumps(out, indent=1))
    print(f"xT: {xt.n_moves} moves, {xt.n_shots} shots, {xt.n_goals} goals, {xt.iterations} iter.")
    print(f"xG: N={xg.n_shots} shots, {xg.n_goals} goals, coef={xg.coef}, CI95={xg.ci95}")
    print(f"written {MODELS_PATH}")


if __name__ == "__main__":
    main()
