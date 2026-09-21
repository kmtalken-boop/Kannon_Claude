"""Building / loading the 16-player roster and its monthly schedule."""
from __future__ import annotations

import yaml

from .data.schedule import default_schedule
from .models import Player


def default_players() -> list[Player]:
    """16 players, equal skill -- a generic fallback roster."""
    return [Player(id=f"Player {i + 1}", name=f"Player {i + 1}", skill=1000.0) for i in range(16)]


def default_roster() -> tuple[list[Player], dict[str, dict[str, list[Player]]]]:
    """Equal-skill players plus a generic (but validated, no repeated
    pairings) 3-month schedule -- used when no config file is given.
    """
    players = default_players()
    return players, default_schedule(players)


def load_roster(path: str) -> tuple[list[Player], dict[str, dict[str, list[Player]]]]:
    """Load 16 players (name + skill) and their monthly schedule from YAML.

    Expects a flat ``players:`` list of ``{name, skill}``. An optional
    ``schedule:`` section (month -> pod label -> 4 names) is used as-is if
    present; otherwise a generic, validated 3-month rotation is generated
    from the player list's order. See config/players_calibrated.yaml for
    the real schedule, or config/players.yaml for the generic version.
    """
    with open(path) as f:
        data = yaml.safe_load(f)

    entries = data.get("players", [])
    if len(entries) != 16:
        raise ValueError(f"expected 16 players, got {len(entries)}")

    players = [
        Player(id=entry["name"], name=entry["name"], skill=float(entry.get("skill", 1000.0)))
        for entry in entries
    ]
    players_by_name = {p.name: p for p in players}
    if len(players_by_name) != len(players):
        raise ValueError("player names must be unique")

    raw_schedule = data.get("schedule")
    if raw_schedule:
        schedule = {
            month: {
                label: [players_by_name[name] for name in names] for label, names in pods.items()
            }
            for month, pods in raw_schedule.items()
        }
    else:
        schedule = default_schedule(players)

    return players, schedule
