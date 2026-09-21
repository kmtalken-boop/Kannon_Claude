"""Predicts the outcome of an arbitrary 4-player matchup.

Unlike ``season.run_season`` (a full 16-player season), this runs just the
one match those 4 specific players would race -- the same
``match.simulate_match`` the rest of the simulator uses, repeated many
times to average out race-to-race and beer-schedule luck. It's the
"pick any 4 people, what would happen" tool: useful for a hypothetical
grudge match, a league-night lineup that doesn't match the real groups, or
sanity-checking two players' relative skill head to head.
"""
from __future__ import annotations

import random
from dataclasses import dataclass

from .match import MatchConfig, simulate_match
from .models import Player


@dataclass
class MatchupEstimate:
    avg_points: dict[str, float]
    win_pct: dict[str, float]  # % of trials that player finished 1st
    trials: int


def estimate_matchup(
    players: list[Player], config: MatchConfig, rng: random.Random, trials: int = 300
) -> MatchupEstimate:
    if len(players) != 4:
        raise ValueError("a matchup is always 4 players")

    totals = {p.id: 0 for p in players}
    wins = {p.id: 0 for p in players}

    for _ in range(trials):
        result = simulate_match(players, config, rng)
        for pid, pts in result.points.items():
            totals[pid] += pts
        wins[result.ranked()[0]] += 1

    return MatchupEstimate(
        avg_points={pid: total / trials for pid, total in totals.items()},
        win_pct={pid: 100.0 * w / trials for pid, w in wins.items()},
        trials=trials,
    )
