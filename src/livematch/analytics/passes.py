"""Average positions and pass networks from event data."""

from __future__ import annotations

from collections import Counter
from typing import Any

from livematch.schema import Event, Team

MIN_EDGE_PASSES = 3


def pass_network(
    events: list[Event],
    team: Team,
    until_frame: int | None = None,
    min_passes: int = MIN_EDGE_PASSES,
) -> dict[str, Any]:
    """Nodes = players at the mean location of their on-ball actions; edges = passes A -> B.

    Coordinates are in the internal system (home attacks towards x = 105).
    """
    locs: dict[str, list[tuple[float, float]]] = {}
    edges: Counter[tuple[str, str]] = Counter()
    for e in events:
        if e.team != team or (until_frame is not None and e.frame_id > until_frame):
            continue
        if e.player_id is not None and e.x is not None and e.y is not None:
            locs.setdefault(e.player_id, []).append((e.x, e.y))
        if e.event_type == "PASS" and e.player_id and e.to_player_id:
            edges[tuple(sorted((e.player_id, e.to_player_id)))] += 1  # undirected
    nodes = [
        {
            "player": pid,
            "x": round(sum(p[0] for p in pts) / len(pts), 2),
            "y": round(sum(p[1] for p in pts) / len(pts), 2),
            "n": len(pts),
        }
        for pid, pts in sorted(locs.items())
    ]
    known = {n["player"] for n in nodes}
    links = [
        {"a": a, "b": b, "count": c}
        for (a, b), c in edges.most_common()
        if c >= min_passes and a in known and b in known
    ]
    return {"team": team.value, "nodes": nodes, "edges": links}
