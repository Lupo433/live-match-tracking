"""Loader for the Metrica Sports sample data (CSV format).

File layout (see docs/data_format.md for details):
    <dir>/<Game>_RawTrackingData_Home_Team.csv
    <dir>/<Game>_RawTrackingData_Away_Team.csv
    <dir>/<Game>_RawEventsData.csv

Tracking CSVs have a 3-line header (team / jersey number / column name), then
``Period, Frame, Time [s], <PlayerN x>, <PlayerN y>, ..., Ball x, Ball y``.
Coordinates are normalised to [0, 1] with the origin in the TOP-left corner.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from livematch.schema import DEFAULT_FPS, PITCH_LENGTH, PITCH_WIDTH, Event, MatchInfo, Player, Team
from livematch.sources.array_source import ArraySource, period_starts


@dataclass(frozen=True)
class _TeamTable:
    numbers: list[int]
    names: list[str]
    frame_ids: np.ndarray
    periods: np.ndarray
    times: np.ndarray
    xy: np.ndarray  # (n, n_players, 2) normalised
    ball: np.ndarray  # (n, 2) normalised


def _read_tracking(path: Path) -> _TeamTable:
    with path.open(newline="") as fh:
        reader = csv.reader(fh)
        _teams = next(reader)
        numbers_row = next(reader)
        names_row = next(reader)
    # player columns start at index 3 and come in (x, y) pairs; the last pair is the ball.
    names: list[str] = []
    numbers: list[int] = []
    for col in range(3, len(names_row) - 2, 2):
        names.append(names_row[col])
        numbers.append(int(numbers_row[col]))
    data = pd.read_csv(path, skiprows=3, header=None).to_numpy(dtype=np.float64)
    n_players = len(names)
    xy = data[:, 3 : 3 + 2 * n_players].reshape(len(data), n_players, 2)
    ball = data[:, 3 + 2 * n_players : 5 + 2 * n_players]
    return _TeamTable(
        numbers=numbers,
        names=names,
        frame_ids=data[:, 1].astype(np.int64),
        periods=data[:, 0].astype(np.int64),
        times=data[:, 2],
        xy=xy,
        ball=ball,
    )


def _to_metres(xy: np.ndarray) -> np.ndarray:
    """Metrica normalised (origin top-left) -> metres (origin bottom-left)."""
    out = np.empty_like(xy, dtype=np.float64)
    out[..., 0] = xy[..., 0] * PITCH_LENGTH
    out[..., 1] = (1.0 - xy[..., 1]) * PITCH_WIDTH
    return out


def _flip(xy: np.ndarray) -> np.ndarray:
    """Rotate by 180 degrees around the centre spot."""
    out = xy.copy()
    out[..., 0] = PITCH_LENGTH - out[..., 0]
    out[..., 1] = PITCH_WIDTH - out[..., 1]
    return out


def find_game_files(directory: Path) -> tuple[Path, Path, Path | None]:
    """Locate home/away tracking and events files inside ``directory``."""
    home = next(directory.glob("*RawTrackingData_Home_Team.csv"), None)
    away = next(directory.glob("*RawTrackingData_Away_Team.csv"), None)
    events = next(directory.glob("*RawEventsData.csv"), None)
    if home is None or away is None:
        raise FileNotFoundError(f"Metrica tracking files not found in {directory}")
    return home, away, events


def load_metrica(
    directory: str | Path,
    match_id: str | None = None,
    title: str | None = None,
) -> ArraySource:
    """Load a Metrica sample game directory into an :class:`ArraySource`.

    The home team is normalised to attack towards x = 105 in every period.
    """
    directory = Path(directory)
    home_p, away_p, events_p = find_game_files(directory)
    home = _read_tracking(home_p)
    away = _read_tracking(away_p)
    if not np.array_equal(home.frame_ids, away.frame_ids):
        raise ValueError("home and away tracking files are not aligned")

    players: list[Player] = []
    for team, table in ((Team.HOME, home), (Team.AWAY, away)):
        # Metrica lists the starting goalkeeper first for each team.
        for k, (num, name) in enumerate(zip(table.numbers, table.names, strict=True)):
            players.append(
                Player(
                    index=len(players),
                    player_id=f"{team.value[0].upper()}{num}",
                    team=team,
                    number=num,
                    name=name,
                    is_goalkeeper=(k == 0),
                )
            )

    positions = _to_metres(np.concatenate([home.xy, away.xy], axis=1))
    ball = _to_metres(home.ball)
    periods = home.periods

    flip_periods = _periods_to_flip(positions[:, : len(home.names)], periods)
    for p in flip_periods:
        mask = periods == p
        positions[mask] = _flip(positions[mask])
        ball[mask] = _flip(ball[mask])

    frame_ids = home.frame_ids
    events = _read_events(events_p, frame_ids, flip_periods) if events_p is not None else []
    times = home.times
    dt = float(np.median(np.diff(times))) if len(times) > 1 else 1 / DEFAULT_FPS
    fps = round(1.0 / dt, 3)
    game = directory.name
    info = MatchInfo(
        match_id=match_id or game.lower(),
        title=title or game.replace("_", " "),
        home_name="Home",
        away_name="Away",
        fps=fps,
        n_frames=len(times),
        duration_s=len(times) / fps,
        period_starts=period_starts(periods),
        source="metrica",
    )
    return ArraySource(info, players, positions, ball, times, periods, events)


def _periods_to_flip(home_positions: np.ndarray, periods: np.ndarray) -> list[int]:
    """Periods where the home team attacks towards x = 0 (its block sits on the right)."""
    flips = []
    for p in np.unique(periods):
        idx = np.flatnonzero(periods == p)[:250]  # first ~10 s of the period
        mean_x = np.nanmean(home_positions[idx, :, 0])
        if mean_x > PITCH_LENGTH / 2:
            flips.append(int(p))
    return flips


def _parse_team(value: object) -> Team | None:
    s = str(value).strip().lower()
    return Team(s) if s in ("home", "away") else None


def _player_id(team: Team | None, value: object) -> str | None:
    s = str(value)
    if team is None or not s.startswith("Player"):
        return None
    return f"{team.value[0].upper()}{s.removeprefix('Player')}"


def _read_events(path: Path, frame_ids: np.ndarray, flip_periods: list[int]) -> list[Event]:
    """Read the events CSV, keeping only events inside the loaded frame range."""
    df = pd.read_csv(path)
    out: list[Event] = []
    first, last = int(frame_ids[0]), int(frame_ids[-1])
    for row in df.itertuples(index=False):
        start_frame = int(row[4])
        if not first <= start_frame <= last:
            continue
        idx = int(np.searchsorted(frame_ids, start_frame))
        if idx >= len(frame_ids) or frame_ids[idx] != start_frame:
            continue  # falls in a gap of a cropped sample
        team = _parse_team(row[0])
        period = int(row[3])
        coords = []
        for xn, yn in ((row[10], row[11]), (row[12], row[13])):
            if pd.isna(xn) or pd.isna(yn):
                coords.append((None, None))
                continue
            xy = _to_metres(np.array([float(xn), float(yn)]))
            if period in flip_periods:
                xy = _flip(xy)
            coords.append((float(xy[0]), float(xy[1])))
        end_t = float(row[7]) if float(row[6]) > 0 else None
        out.append(
            Event(
                event_type=str(row[1]),
                subtype="" if pd.isna(row[2]) else str(row[2]),
                team=team,
                player_id=_player_id(team, row[8]),
                period=period,
                timestamp=float(row[5]),
                frame_id=idx,
                x=coords[0][0],
                y=coords[0][1],
                end_x=coords[1][0],
                end_y=coords[1][1],
                end_timestamp=end_t,
            )
        )
    return out
