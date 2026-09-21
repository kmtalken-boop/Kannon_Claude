"""Regular-season (league) phase.

Groups are redrawn every month -- see ``data/schedule.py`` -- so there's
no persistent "group" a player accumulates standings within. Each
player's season total is just their own points summed across their 3
different monthly matches (their "3 placement matches"), against 3
different sets of opponents.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field

from .match import MatchConfig, MatchResult, simulate_match
from .models import Player


@dataclass
class LeagueResult:
    season_points: dict[str, int] = field(default_factory=dict)
    monthly_results: dict[str, dict[str, MatchResult]] = field(default_factory=dict)


def run_league_phase(
    schedule: dict[str, dict[str, list[Player]]], config: MatchConfig, rng: random.Random
) -> LeagueResult:
    result = LeagueResult()
    for month, pods in schedule.items():
        result.monthly_results[month] = {}
        for pod_label, players in pods.items():
            if len(players) != 4:
                raise ValueError(f"{month} {pod_label} must have exactly 4 players")
            match = simulate_match(players, config, rng)
            result.monthly_results[month][pod_label] = match
            for pid, pts in match.points.items():
                result.season_points[pid] = result.season_points.get(pid, 0) + pts
    return result
