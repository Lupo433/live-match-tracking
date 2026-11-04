"""Live xT / xG accumulation as the replay passes the events."""

from __future__ import annotations

import math

from livematch.analytics.geometry import event_end, event_start
from livematch.analytics.models import get_models
from livematch.analytics.xt import CARRY_MIN_DISTANCE
from livematch.schema import Event


class ThreatTracker:
    """Cumulative xT generated (passes + carries) and xG per team and player.

    Uses the shipped demonstrative models; state is a few floats, so it is
    cheap to checkpoint.
    """

    def __init__(self) -> None:
        self.xt = {"home": 0.0, "away": 0.0}
        self.xg = {"home": 0.0, "away": 0.0}
        self.player_xt: dict[str, float] = {}
        self._last_pass: Event | None = None

    def update(self, new_events: list[Event]) -> None:
        if not new_events:
            return
        models = get_models()
        for e in new_events:
            if e.team is None:
                continue
            team = e.team.value
            start = event_start(e)
            # carry: receiver of the previous pass acts from a different place
            lp = self._last_pass
            if (
                lp is not None
                and lp.team == e.team
                and lp.to_player_id is not None
                and e.player_id == lp.to_player_id
                and lp.period == e.period
                and start is not None
            ):
                lend = event_end(lp)
                if lend is not None and math.dist(lend, start) >= CARRY_MIN_DISTANCE:
                    self._credit(team, e.player_id, models.xt.added(lend, start))
            self._last_pass = None
            if e.event_type == "PASS":
                end = event_end(e)
                if start is not None and end is not None:
                    self._credit(team, e.player_id, models.xt.added(start, end))
                    self._last_pass = e
            elif e.event_type == "SHOT" and start is not None:
                self.xg[team] += models.xg.predict(*start)

    @staticmethod
    def xg_of(e: Event) -> float:
        start = event_start(e)
        return get_models().xg.predict(*start) if start is not None else 0.0

    def _credit(self, team: str, pid: str | None, value: float) -> None:
        self.xt[team] += value
        if pid is not None:
            self.player_xt[pid] = self.player_xt.get(pid, 0.0) + value
