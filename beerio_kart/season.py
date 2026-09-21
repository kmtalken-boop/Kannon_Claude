"""Orchestrates one full season: the league phase, then the playoffs."""
from __future__ import annotations

import random
from dataclasses import dataclass

from .league import LeagueResult, run_league_phase
from .match import MatchConfig
from .models import Player
from .playoffs import PlayoffResult, run_playoffs


@dataclass
class SeasonResult:
    league: LeagueResult
    playoffs: PlayoffResult


def run_season(
    schedule: dict[str, dict[str, list[Player]]],
    config: MatchConfig,
    rng: random.Random,
    known_results: dict[str, list[dict[str, int]]] | None = None,
) -> SeasonResult:
    players_by_id = {p.id: p for pods in schedule.values() for players in pods.values() for p in players}
    league_result = run_league_phase(schedule, config, rng, known_results=known_results)
    playoff_result = run_playoffs(league_result.season_points, players_by_id, config, rng)
    return SeasonResult(league=league_result, playoffs=playoff_result)
