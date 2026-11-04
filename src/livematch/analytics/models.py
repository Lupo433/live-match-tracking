"""Load the fitted (demonstrative) xT / xG models shipped with the package.

``models.json`` is produced by ``python scripts/fit_models.py`` from the two
public Metrica matches. If it is missing, neutral fallbacks are used.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np

from livematch.analytics.xg import XGModel
from livematch.analytics.xt import XTModel

MODELS_PATH = Path(__file__).with_name("models.json")


@dataclass(frozen=True)
class Models:
    xt: XTModel
    xg: XGModel
    meta: dict[str, Any]


def _fallback() -> Models:
    # xT grows linearly towards the opponent goal; xG from a textbook-like logistic curve
    xt = XTModel(nx=16, ny=12, grid=np.tile(np.linspace(0.0, 0.2, 16) ** 2 * 5, (12, 1)))
    return Models(xt, XGModel(intercept=-1.2, coef=[-0.11, 1.2]), {"source": "fallback"})


@lru_cache(maxsize=1)
def get_models() -> Models:
    if not MODELS_PATH.exists():
        return _fallback()
    d = json.loads(MODELS_PATH.read_text())
    return Models(XTModel.from_dict(d["xt"]), XGModel.from_dict(d["xg"]), d.get("meta", {}))
