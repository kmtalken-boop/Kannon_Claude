"""Single-race simulation using a Plackett-Luce ranking model.

Effective (post-beer) skill is turned into a full finishing order via the
Gumbel-max trick: for each racer, draw ``log(skill) + noise`` and sort
descending. This produces exactly a Plackett-Luce ranking (equivalent to
picking 1st place proportional to strength, then 2nd among the rest, and so
on) in a single pass. ``chaos_scale`` stands in for the game's own
randomness -- items, blue shells, bananas -- that narrows the gap between a
strong and weak driver; turn it up to make skill matter less.

Every race is a full 12-racer MKWii field -- the 4 human players plus 8
CPU racers filling out the rest of the grid (see ``match.py``) -- scored
with MKWii's own 12-place points table.
"""
from __future__ import annotations

import math
import random

POSITION_POINTS = {1: 15, 2: 12, 3: 10, 4: 8, 5: 7, 6: 6, 7: 5, 8: 4, 9: 3, 10: 2, 11: 1, 12: 0}


def simulate_race(effective_skill: dict[str, float], chaos_scale: float, rng: random.Random) -> list[str]:
    """Return racer ids ordered 1st through last."""

    def score(pid: str) -> float:
        u = min(max(rng.random(), 1e-12), 1.0 - 1e-12)
        noise = -math.log(-math.log(u))
        return math.log(max(effective_skill[pid], 1e-6)) + chaos_scale * noise

    return sorted(effective_skill, key=score, reverse=True)
