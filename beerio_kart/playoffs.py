"""Playoff bracket.

The top 2 finishers from each of the 4 groups (8 players total) qualify
and are seeded 1-8 by total league points, compared directly across
groups. Seeds {1, 2, 7, 8} form one 4-player playoff group and seeds
{3, 4, 5, 6} form the other ("3-6 play each other in a semifinal"). Each
group plays one fresh 32-race match (its own new 8-beer-per-player
schedule); the top 2 finishers from each of those two matches (4 players
total) advance to a single winner-take-all final match.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field

from .league import GroupResult
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


def seed_playoffs(
    group_results: dict[str, GroupResult], rng: random.Random
) -> list[str]:
    """Return the 8 qualifiers ordered by seed (1 first)."""
    qualifiers: list[str] = []
    points_lookup: dict[str, int] = {}
    for group in group_results.values():
        qualifiers.extend(group.standings()[:2])
        points_lookup.update(group.season_points)

    # Shuffle first so that exact point ties break randomly rather than by
    # insertion order (Python's sort is stable).
    rng.shuffle(qualifiers)
    qualifiers.sort(key=lambda pid: -points_lookup[pid])
    return qualifiers


def run_playoffs(
    group_results: dict[str, GroupResult],
    players_by_id: dict[str, Player],
    config: MatchConfig,
    rng: random.Random,
) -> PlayoffResult:
    seeds = seed_playoffs(group_results, rng)
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
