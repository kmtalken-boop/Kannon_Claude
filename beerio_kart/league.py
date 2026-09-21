"""Regular-season (group) phase.

16 players sit in 4 fixed groups of 4. Each group plays a match once a
month for 3 months, always against the same 3 groupmates -- so nobody ever
races an opponent outside their group, which is what satisfies "no player
plays another more than once in league play." Standings are the sum of
points across the group's 3 matches ("total points over your 3 placement
matches"); the top 2 finishers in each group advance to the playoffs.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field

from .match import MatchConfig, MatchResult, simulate_match
from .models import Player

MONTHS_PER_SEASON = 3


@dataclass
class GroupResult:
    name: str
    players: list[Player]
    season_points: dict[str, int] = field(default_factory=dict)
    season_wins: dict[str, int] = field(default_factory=dict)
    match_results: list[MatchResult] = field(default_factory=list)

    def standings(self) -> list[str]:
        """Player ids ordered 1st through 4th in the group."""
        return sorted(
            (p.id for p in self.players),
            key=lambda pid: (-self.season_points[pid], -self.season_wins[pid]),
        )


def run_group(name: str, players: list[Player], config: MatchConfig, rng: random.Random) -> GroupResult:
    if len(players) != 4:
        raise ValueError(f"group {name} must have exactly 4 players")

    result = GroupResult(name=name, players=players)
    result.season_points = {p.id: 0 for p in players}
    result.season_wins = {p.id: 0 for p in players}

    for _month in range(MONTHS_PER_SEASON):
        match = simulate_match(players, config, rng)
        result.match_results.append(match)
        for pid, pts in match.points.items():
            result.season_points[pid] += pts
        for pid, wins in match.race_wins.items():
            result.season_wins[pid] += wins

    return result


def run_league_phase(
    groups: dict[str, list[Player]], config: MatchConfig, rng: random.Random
) -> dict[str, GroupResult]:
    return {name: run_group(name, players, config, rng) for name, players in groups.items()}
