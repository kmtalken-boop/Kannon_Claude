"""Runs the season simulator many times to estimate outcome probabilities."""
from __future__ import annotations

import random
from dataclasses import dataclass

from .match import MatchConfig
from .models import Player
from .season import run_season


@dataclass
class PlayerStats:
    name: str
    group: str
    sims: int = 0
    playoff_appearances: int = 0
    finals_appearances: int = 0
    championships: int = 0
    total_season_points: float = 0.0

    def as_row(self) -> dict:
        pct = lambda n: 100.0 * n / self.sims if self.sims else 0.0
        return {
            "name": self.name,
            "group": self.group,
            "avg_points": self.total_season_points / self.sims if self.sims else 0.0,
            "playoff_pct": pct(self.playoff_appearances),
            "finals_pct": pct(self.finals_appearances),
            "champion_pct": pct(self.championships),
        }


def run_monte_carlo(
    groups: dict[str, list[Player]], config: MatchConfig, n_sims: int, rng: random.Random
) -> dict[str, PlayerStats]:
    stats: dict[str, PlayerStats] = {
        p.id: PlayerStats(name=p.name, group=group_name)
        for group_name, players in groups.items()
        for p in players
    }

    for _ in range(n_sims):
        result = run_season(groups, config, rng)

        for group_result in result.groups.values():
            for pid, pts in group_result.season_points.items():
                s = stats[pid]
                s.sims += 1
                s.total_season_points += pts
            for pid in group_result.standings()[:2]:
                stats[pid].playoff_appearances += 1

        for pid in result.playoffs.finalists:
            stats[pid].finals_appearances += 1
        stats[result.playoffs.champion].championships += 1

    return stats
