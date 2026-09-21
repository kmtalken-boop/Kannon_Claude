"""Orchestrates one full season: the group phase, then the playoffs."""
from __future__ import annotations

import random
from dataclasses import dataclass

from .league import GroupResult, run_league_phase
from .match import MatchConfig
from .models import Player
from .playoffs import PlayoffResult, run_playoffs


@dataclass
class SeasonResult:
    groups: dict[str, GroupResult]
    playoffs: PlayoffResult


def run_season(
    groups: dict[str, list[Player]], config: MatchConfig, rng: random.Random
) -> SeasonResult:
    players_by_id = {p.id: p for plist in groups.values() for p in plist}
    group_results = run_league_phase(groups, config, rng)
    playoff_result = run_playoffs(group_results, players_by_id, config, rng)
    return SeasonResult(groups=group_results, playoffs=playoff_result)
