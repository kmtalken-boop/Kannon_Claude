"""Playoff bracket.

The top 8 of all 16 players by total season points qualify, seeded 1-8
directly by that total (there's no group standings step -- see
``league.py``). Seeds {1, 2, 7, 8} form one 4-player playoff group and
seeds {3, 4, 5, 6} form the other ("3-6 play each other in a semifinal").
Each group plays one fresh 32-race match; the top 2 finishers from each
of those two matches (4 players total) advance to a single
winner-take-all final match.
"""
from __future__ import annotations

import random
from dataclasses import dataclass

from .match import MatchConfig, MatchResult, simulate_match
from .models import Player


@dataclass
class PlayoffResult:
    seeds: list[str]                                  # seed 1..8, best to worst
    bracket_top: MatchResult                           # seeds 1, 2, 7, 8
    bracket_bottom: MatchResult                         # seeds 3, 4, 5, 6
    finalists: list[str]
    final: MatchResult
    champion: str


def seed_playoffs(season_points: dict[str, int], rng: random.Random) -> list[str]:
    """Return the top 8 player ids ordered by seed (1 first)."""
    ids = list(season_points)
    # Shuffle first so that exact point ties break randomly rather than by
    # insertion order (Python's sort is stable).
    rng.shuffle(ids)
    ids.sort(key=lambda pid: -season_points[pid])
    return ids[:8]


def run_playoffs(
    season_points: dict[str, int],
    players_by_id: dict[str, Player],
    config: MatchConfig,
    rng: random.Random,
) -> PlayoffResult:
    seeds = seed_playoffs(season_points, rng)
    top_group_ids = [seeds[0], seeds[1], seeds[6], seeds[7]]
    bottom_group_ids = [seeds[2], seeds[3], seeds[4], seeds[5]]

    top_match = simulate_match([players_by_id[pid] for pid in top_group_ids], config, rng)
    bottom_match = simulate_match([players_by_id[pid] for pid in bottom_group_ids], config, rng)

    finalists = top_match.ranked()[:2] + bottom_match.ranked()[:2]

    final_match = simulate_match([players_by_id[pid] for pid in finalists], config, rng)
    champion = final_match.ranked()[0]

    return PlayoffResult(
        seeds=seeds,
        bracket_top=top_match,
        bracket_bottom=bottom_match,
        finalists=finalists,
        final=final_match,
        champion=champion,
    )
