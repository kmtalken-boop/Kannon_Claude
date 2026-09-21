"""Building / loading the 16-player roster and its 4 fixed groups."""
from __future__ import annotations

import yaml

from .models import Player


def default_roster() -> dict[str, list[Player]]:
    """16 players, equal skill, split into 4 groups of 4 (A-D)."""
    groups: dict[str, list[Player]] = {}
    for g in range(4):
        group_name = chr(ord("A") + g)
        players = [
            Player(id=f"{group_name}{i + 1}", name=f"Player {g * 4 + i + 1}", skill=1000.0)
            for i in range(4)
        ]
        groups[group_name] = players
    return groups


def load_roster(path: str) -> dict[str, list[Player]]:
    """Load a roster from YAML: 4 groups of 4 {name, skill} entries.

    See config/players.yaml for the expected format.
    """
    with open(path) as f:
        data = yaml.safe_load(f)

    raw_groups = data.get("groups", {})
    if len(raw_groups) != 4:
        raise ValueError(f"expected 4 groups, got {len(raw_groups)}")

    groups: dict[str, list[Player]] = {}
    for group_name, entries in raw_groups.items():
        if len(entries) != 4:
            raise ValueError(f"group {group_name} must have exactly 4 players, got {len(entries)}")
        groups[group_name] = [
            Player(
                id=f"{group_name}_{entry['name']}",
                name=entry["name"],
                skill=float(entry.get("skill", 1000.0)),
            )
            for entry in entries
        ]
    return groups
