"""Event counters that advance with the replay clock."""

from __future__ import annotations

from livematch.schema import Event, Team

COUNTERS = ("goals", "shots", "on_target", "passes", "fouls", "cards", "corners")


def _new() -> dict[str, int]:
    return dict.fromkeys(COUNTERS, 0)


class EventTracker:
    """Counts events up to the current frame (events must be sorted by frame)."""

    def __init__(self, events: list[Event]) -> None:
        self._events = events
        self._next = 0
        self._pending_goals: list[Event] = []  # shot seen, ball not over the line yet
        self.counts: dict[str, dict[str, int]] = {"home": _new(), "away": _new()}

    def __deepcopy__(self, memo: dict) -> EventTracker:
        # the event list is shared (read-only); only the cursor and counters are copied
        new = EventTracker.__new__(EventTracker)
        new._events = self._events
        new._next = self._next
        new._pending_goals = list(self._pending_goals)
        new.counts = {k: dict(v) for k, v in self.counts.items()}
        return new

    def update(self, frame_id: int) -> list[Event]:
        """Consume all events with ``frame_id <= frame_id``; returns the new ones."""
        new: list[Event] = []
        while self._next < len(self._events) and self._events[self._next].frame_id <= frame_id:
            e = self._events[self._next]
            self._next += 1
            new.append(e)
            if e.team is None:
                continue
            c = self.counts[e.team.value]
            sub = e.subtype.upper()
            if e.event_type == "SHOT":
                c["shots"] += 1
                if "ON TARGET" in sub or "GOAL" in sub:
                    c["on_target"] += 1
                if e.is_goal:
                    self._pending_goals.append(e)
            elif e.event_type == "PASS":
                c["passes"] += 1
            elif e.event_type == "FAULT RECEIVED":
                # the foul is committed by the other team
                other = Team.AWAY if e.team == Team.HOME else Team.HOME
                self.counts[other.value]["fouls"] += 1
            elif e.event_type == "CARD":
                c["cards"] += 1
            elif e.event_type == "SET PIECE" and "CORNER" in sub:
                c["corners"] += 1
        if self._pending_goals:
            still = []
            for g in self._pending_goals:
                if g.effective_frame <= frame_id:
                    self.counts[g.team.value]["goals"] += 1  # type: ignore[union-attr]
                else:
                    still.append(g)
            self._pending_goals = still
        return new
