"""Simulates one 32-race match between a fixed group of 4 players."""
from __future__ import annotations

import math
import random
from dataclasses import dataclass

from .beer import draw_beer_schedule
from .models import MatchResult, Player
from .race import POSITION_POINTS, simulate_race


@dataclass
class MatchConfig:
    races_per_match: int = 32       # 8 cups x 4 races, standard MKWii GP structure
    beers_per_player: int = 8
    impairment_coef: float = 0.12   # how hard accumulated beers drag down effective skill
    decay_rate: float = 0.85        # per-race multiplicative decay of impairment (sobering up)
    chaos_scale: float = 1.0        # in-game randomness (items etc.); higher flattens skill gaps


def simulate_match(players: list[Player], config: MatchConfig, rng: random.Random) -> MatchResult:
    if len(players) != 4:
        raise ValueError("a match is always a 4-player field")

    ids = [p.id for p in players]
    skill = {p.id: p.skill for p in players}
    impairment = {pid: 0.0 for pid in ids}
    points = {pid: 0 for pid in ids}
    race_wins = {pid: 0 for pid in ids}
    peak_impairment = {pid: 0.0 for pid in ids}
    schedules = {
        pid: draw_beer_schedule(rng, config.races_per_match, config.beers_per_player) for pid in ids
    }

    for race_num in range(1, config.races_per_match + 1):
        for pid in ids:
            impairment[pid] *= config.decay_rate

        effective = {
            pid: skill[pid] * math.exp(-config.impairment_coef * impairment[pid]) for pid in ids
        }
        order = simulate_race(effective, config.chaos_scale, rng)
        for rank, pid in enumerate(order, start=1):
            points[pid] += POSITION_POINTS[rank]
        race_wins[order[0]] += 1

        for pid in ids:
            if race_num in schedules[pid]:
                impairment[pid] += 1.0
            peak_impairment[pid] = max(peak_impairment[pid], impairment[pid])

    return MatchResult(points=points, race_wins=race_wins, peak_impairment=peak_impairment)
