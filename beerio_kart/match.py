"""Simulates one 32-race match between a fixed group of 4 human players.

Every individual race is a full 12-racer MKWii field: the 4 humans plus 8
CPU racers filling out the rest of the grid, scored on MKWii's real
12-place points table. A human can finish anywhere from 1st to 12th
depending on both the other 3 humans and the 8 CPUs that race -- CPUs
don't accumulate points themselves (they're not one of the 4 people this
league tracks), but where they finish absorbs points that would otherwise
have gone to a human, which is what lets a weak human's match total drop
into double digits even though the per-race point scale only goes down to
5th-8th place.
"""
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
    chaos_scale: float = 1.15       # in-game randomness (items etc.); higher flattens skill gaps
    cpu_skill: float = 200.0        # fixed skill of each of the 8 CPU racers filling out the field
    cpu_count: int = 8              # 4 humans + 8 CPUs = MKWii's real 12-racer field


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
    cpu_ids = [f"__cpu{i}__" for i in range(config.cpu_count)]

    for race_num in range(1, config.races_per_match + 1):
        for pid in ids:
            impairment[pid] *= config.decay_rate

        effective = {
            pid: skill[pid] * math.exp(-config.impairment_coef * impairment[pid]) for pid in ids
        }
        for cpu_id in cpu_ids:
            effective[cpu_id] = config.cpu_skill

        order = simulate_race(effective, config.chaos_scale, rng)
        for rank, pid in enumerate(order, start=1):
            if pid in points:
                points[pid] += POSITION_POINTS[rank]
        if order[0] in race_wins:
            race_wins[order[0]] += 1

        for pid in ids:
            if race_num in schedules[pid]:
                impairment[pid] += 1.0
            peak_impairment[pid] = max(peak_impairment[pid], impairment[pid])

    return MatchResult(points=points, race_wins=race_wins, peak_impairment=peak_impairment)
