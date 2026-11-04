"""Expected Threat (xT, Karun Singh 2018) fitted by value iteration on event data.

For every cell c of an ``nx`` x ``ny`` grid (team always attacking towards x = 105):

    xT(c) = s(c) * g(c) + m(c) * sum_c' T(c -> c') * xT(c')

* s(c): share of actions in c that are shots; g(c): goals / shots in c;
* m(c): share of actions in c that are moves (passes + carries, successful or not);
* T(c -> c'): successful moves from c ending in c', divided by all moves from c
  (failed moves lose the ball, so they contribute zero).

The value added by a successful pass or carry is ``xT(end) - xT(start)``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from livematch.analytics.geometry import event_end, event_start
from livematch.schema import PITCH_LENGTH, PITCH_WIDTH, Event

CARRY_MIN_DISTANCE = 3.0  # metres between reception and next action to count a carry
FAILED_MOVE_TYPES = {"BALL LOST"}


@dataclass(frozen=True)
class Move:
    start: tuple[float, float]
    end: tuple[float, float] | None  # None = unsuccessful (ball lost)
    event: Event | None = None
    kind: str = "pass"


@dataclass
class XTModel:
    """A fitted xT grid (rows = y from 0 upwards, columns = x)."""

    nx: int = 16
    ny: int = 12
    grid: np.ndarray = field(default_factory=lambda: np.zeros((12, 16)))
    n_moves: int = 0
    n_shots: int = 0
    n_goals: int = 0
    iterations: int = 0

    def cell(self, x: float, y: float) -> tuple[int, int]:
        ix = min(max(int(x / PITCH_LENGTH * self.nx), 0), self.nx - 1)
        iy = min(max(int(y / PITCH_WIDTH * self.ny), 0), self.ny - 1)
        return iy, ix

    def value(self, x: float, y: float) -> float:
        return float(self.grid[self.cell(x, y)])

    def added(self, start: tuple[float, float], end: tuple[float, float]) -> float:
        return self.value(*end) - self.value(*start)

    def to_dict(self) -> dict:
        return {
            "nx": self.nx,
            "ny": self.ny,
            "grid": np.round(self.grid, 5).tolist(),
            "n_moves": self.n_moves,
            "n_shots": self.n_shots,
            "n_goals": self.n_goals,
            "iterations": self.iterations,
        }

    @classmethod
    def from_dict(cls, d: dict) -> XTModel:
        return cls(
            nx=d["nx"],
            ny=d["ny"],
            grid=np.array(d["grid"], dtype=float),
            n_moves=d.get("n_moves", 0),
            n_shots=d.get("n_shots", 0),
            n_goals=d.get("n_goals", 0),
            iterations=d.get("iterations", 0),
        )


def extract_moves(events: list[Event]) -> list[Move]:
    """Successful passes, carries (reception -> next action) and failed moves."""
    moves: list[Move] = []
    evs = sorted(events, key=lambda e: e.timestamp)
    for i, e in enumerate(evs):
        start = event_start(e)
        if start is None:
            continue
        if e.event_type == "PASS":
            end = event_end(e)
            if end is not None:
                moves.append(Move(start, end, e, "pass"))
                # carry: the receiver's next action starts somewhere else
                nxt = evs[i + 1] if i + 1 < len(evs) else None
                if (
                    nxt is not None
                    and nxt.team == e.team
                    and e.to_player_id is not None
                    and nxt.player_id == e.to_player_id
                    and nxt.period == e.period
                ):
                    nstart = event_start(nxt)
                    if nstart is not None and math.dist(end, nstart) >= CARRY_MIN_DISTANCE:
                        moves.append(Move(end, nstart, None, "carry"))
        elif e.event_type in FAILED_MOVE_TYPES:
            moves.append(Move(start, None, e, "lost"))
    return moves


def fit_xt(
    events: list[Event], nx: int = 16, ny: int = 12, tol: float = 1e-6, max_iter: int = 500
) -> XTModel:
    """Fit the xT grid by value iteration."""
    model = XTModel(nx=nx, ny=ny, grid=np.zeros((ny, nx)))
    n_cells = nx * ny
    shots = np.zeros(n_cells)
    goals = np.zeros(n_cells)
    moves = np.zeros(n_cells)
    trans = np.zeros((n_cells, n_cells))

    def idx(p: tuple[float, float]) -> int:
        iy, ix = model.cell(*p)
        return iy * nx + ix

    for e in events:
        if e.event_type == "SHOT" and (p := event_start(e)) is not None:
            shots[idx(p)] += 1
            goals[idx(p)] += e.is_goal
    all_moves = extract_moves(events)
    for mv in all_moves:
        a = idx(mv.start)
        moves[a] += 1
        if mv.end is not None:
            trans[a, idx(mv.end)] += 1
    total = shots + moves
    with np.errstate(invalid="ignore", divide="ignore"):
        s = np.where(total > 0, shots / total, 0.0)
        m = np.where(total > 0, moves / total, 0.0)
        g = np.where(shots > 0, goals / shots, 0.0)
        t = np.where(moves[:, None] > 0, trans / moves[:, None], 0.0)
    xt = np.zeros(n_cells)
    it = 0
    for it in range(1, max_iter + 1):  # noqa: B007
        new = s * g + m * (t @ xt)
        if np.max(np.abs(new - xt)) < tol:
            xt = new
            break
        xt = new
    model.grid = xt.reshape(ny, nx)
    model.n_moves = int(moves.sum())
    model.n_shots = int(shots.sum())
    model.n_goals = int(goals.sum())
    model.iterations = it
    return model


def credited_values(model: XTModel, events: list[Event]) -> list[tuple[Event, str, float]]:
    """``(event, player_id, xT added)`` for every successful move.

    A pass is credited to the passer at the pass event; a carry is credited to
    the carrier at the event that ends it (his next action).
    """
    out: list[tuple[Event, str, float]] = []
    evs = sorted(events, key=lambda e: e.timestamp)
    for i, e in enumerate(evs):
        if e.event_type != "PASS" or e.player_id is None:
            continue
        start, end = event_start(e), event_end(e)
        if start is None or end is None:
            continue
        out.append((e, e.player_id, model.added(start, end)))
        nxt = evs[i + 1] if i + 1 < len(evs) else None
        if (
            nxt is not None
            and e.to_player_id is not None
            and nxt.player_id == e.to_player_id
            and nxt.team == e.team
            and nxt.period == e.period
        ):
            nstart = event_start(nxt)
            if nstart is not None and math.dist(end, nstart) >= CARRY_MIN_DISTANCE:
                out.append((nxt, e.to_player_id, model.added(end, nstart)))
    return out


def player_xt(model: XTModel, events: list[Event]) -> dict[str, float]:
    """Total xT generated by each player (passes as passer, carries as carrier)."""
    totals: dict[str, float] = {}
    for _, pid, val in credited_values(model, events):
        totals[pid] = totals.get(pid, 0.0) + val
    return totals
