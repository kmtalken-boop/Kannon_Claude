"""The beer mechanic.

Each player must drink exactly ``beers_per_player`` beers over the
``races_per_match`` races in a match, at whatever pace they personally
choose -- it's self-paced, not assigned by anything external. (The
league's own "random selector" just shuffles the order the 32 races are
played in; since races here are symmetric/exchangeable, that ordering has
no effect on the simulation and isn't modeled separately.) We have no
data on any individual's real pacing habits, and pace clearly varies
person to person, so each player's beer timing is drawn independently at
random here -- a stand-in for that unknown personal pacing, not a claim
that some outside mechanism is choosing it for them. A beer adds one unit
of impairment; impairment decays a little every race (standing in for
metabolizing the alcohol) and drags down a player's effective skill for
the rest of the session. Impairment resets to zero at the start of every
match, since each match is treated as its own drinking session.
"""
from __future__ import annotations

import random


def draw_beer_schedule(rng: random.Random, races_per_match: int, beers_per_player: int) -> set[int]:
    """Return the set of 1-indexed race numbers after which a beer is drunk."""
    if beers_per_player > races_per_match:
        raise ValueError("cannot drink more beers than there are races")
    return set(rng.sample(range(1, races_per_match + 1), beers_per_player))
