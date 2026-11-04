"""Demonstrative Expected Goals model: L2-regularised logistic regression on
shot distance and angle only (no extra features, to limit over-fitting).

With two public matches there are only ~50 shots: the model is NOT predictive.
We report N, the number of goals and bootstrap 95% confidence intervals of the
coefficients, which are (honestly) wide.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy.optimize import minimize

from livematch.analytics.geometry import event_start, shot_angle, shot_distance
from livematch.schema import Event

FEATURES = ("distance_m", "angle_rad")
L2 = 1.0  # ridge penalty on standardised coefficients (not on the intercept)


@dataclass
class XGModel:
    intercept: float = -1.0
    coef: list[float] = field(default_factory=lambda: [-0.1, 1.0])  # per raw feature unit
    ci95: dict[str, list[float]] = field(default_factory=dict)
    n_shots: int = 0
    n_goals: int = 0
    l2: float = L2
    label: str = "modello dimostrativo"

    def predict(self, x: float, y: float) -> float:
        z = self.intercept + self.coef[0] * shot_distance(x, y) + self.coef[1] * shot_angle(x, y)
        return float(1.0 / (1.0 + np.exp(-z)))

    def to_dict(self) -> dict:
        return {
            "intercept": self.intercept,
            "coef": dict(zip(FEATURES, self.coef, strict=True)),
            "ci95": self.ci95,
            "n_shots": self.n_shots,
            "n_goals": self.n_goals,
            "l2": self.l2,
            "label": self.label,
        }

    @classmethod
    def from_dict(cls, d: dict) -> XGModel:
        return cls(
            intercept=d["intercept"],
            coef=[d["coef"][f] for f in FEATURES],
            ci95=d.get("ci95", {}),
            n_shots=d.get("n_shots", 0),
            n_goals=d.get("n_goals", 0),
            l2=d.get("l2", L2),
            label=d.get("label", "modello dimostrativo"),
        )


def shot_features(events: list[Event]) -> tuple[np.ndarray, np.ndarray]:
    """Feature matrix (distance, angle) and goal labels of all located shots."""
    rows, labels = [], []
    for e in events:
        if e.event_type != "SHOT":
            continue
        p = event_start(e)
        if p is None:
            continue
        rows.append((shot_distance(*p), shot_angle(*p)))
        labels.append(1.0 if e.is_goal else 0.0)
    return np.array(rows, dtype=float).reshape(-1, 2), np.array(labels)


def _fit_standardised(xs: np.ndarray, y: np.ndarray, l2: float) -> np.ndarray:
    def loss(w: np.ndarray) -> float:
        z = w[0] + xs @ w[1:]
        # log(1 + e^z) - y z, numerically stable
        return float(np.sum(np.logaddexp(0, z) - y * z) + l2 * np.sum(w[1:] ** 2))

    return minimize(loss, np.zeros(xs.shape[1] + 1), method="BFGS").x


def fit_xg(events: list[Event], l2: float = L2, n_boot: int = 500, seed: int = 0) -> XGModel:
    x, y = shot_features(events)
    if len(y) < 5 or y.sum() == 0:
        raise ValueError("not enough shots/goals to fit an xG model")
    mu, sd = x.mean(axis=0), x.std(axis=0) + 1e-9
    w = _fit_standardised((x - mu) / sd, y, l2)
    coef = w[1:] / sd
    intercept = w[0] - float(np.sum(w[1:] * mu / sd))
    rng = np.random.default_rng(seed)
    boots = []
    for _ in range(n_boot):
        k = rng.integers(0, len(y), len(y))
        if y[k].sum() == 0:
            continue
        wb = _fit_standardised((x[k] - mu) / sd, y[k], l2)
        boots.append(wb[1:] / sd)
    b = np.array(boots)
    ci = {
        f: [
            round(float(np.percentile(b[:, j], 2.5)), 4),
            round(float(np.percentile(b[:, j], 97.5)), 4),
        ]
        for j, f in enumerate(FEATURES)
    }
    return XGModel(
        intercept=float(intercept),
        coef=[float(c) for c in coef],
        ci95=ci,
        n_shots=int(len(y)),
        n_goals=int(y.sum()),
        l2=l2,
    )
