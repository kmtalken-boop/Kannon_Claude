"""Projects the rest of the season from the real current standings.

Unlike ``monte_carlo.run_monte_carlo`` (which simulates a full season from
scratch), this starts every player at their actual banked points
(``data/current_standings.py``) and only simulates the pods nobody has
played yet, then seeds the playoffs off the resulting totals. It's "given
where things actually stand today, what happens next" rather than "what
would a hypothetical season look like."
"""
from __future__ import annotations

import random
from dataclasses import dataclass

from .data.current_standings import CURRENT_STANDINGS, REMAINING_FIXTURES
from .match import MatchConfig, simulate_match
from .models import Player
from .playoffs import run_playoffs


@dataclass
class ProjectedStats:
    name: str
    banked_points: int
    sims: int = 0
    total_final_points: float = 0.0
    playoff_appearances: int = 0
    finals_appearances: int = 0
    championships: int = 0

    def as_row(self) -> dict:
        pct = lambda n: 100.0 * n / self.sims if self.sims else 0.0
        return {
            "name": self.name,
            "banked_points": self.banked_points,
            "avg_final_points": self.total_final_points / self.sims if self.sims else 0.0,
            "playoff_pct": pct(self.playoff_appearances),
            "finals_pct": pct(self.finals_appearances),
            "champion_pct": pct(self.championships),
        }


def run_current_projection(
    players_by_name: dict[str, Player], config: MatchConfig, n_sims: int, rng: random.Random
) -> dict[str, ProjectedStats]:
    stats = {
        name: ProjectedStats(name=name, banked_points=points)
        for name, (_games, points) in CURRENT_STANDINGS.items()
    }

    for _ in range(n_sims):
        totals = {name: points for name, (_games, points) in CURRENT_STANDINGS.items()}

        for _label, names in REMAINING_FIXTURES:
            players = [players_by_name[n] for n in names]
            match = simulate_match(players, config, rng)
            for pid, pts in match.points.items():
                totals[pid] += pts

        for name, total in totals.items():
            s = stats[name]
            s.sims += 1
            s.total_final_points += total

        playoff_result = run_playoffs(totals, players_by_name, config, rng)
        for pid in playoff_result.seeds:
            stats[pid].playoff_appearances += 1
        for pid in playoff_result.finalists:
            stats[pid].finals_appearances += 1
        stats[playoff_result.champion].championships += 1

    return stats
