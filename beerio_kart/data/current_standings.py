"""The league's real current standings, as reported directly by the user
(a screenshot of the standings table), as of 2026-11-15.

Unlike ``SEASON_2_KNOWN_RESULTS`` (per-match points for specific pods),
this is each player's *cumulative* season total plus how many of their 3
scheduled matches they've personally played. Games-played isn't uniform
across players because pods complete at different paces, and a few
pods clearly ran with a substitute standing in for an absent regular
(the same pattern as "Zynny"/"Jack (sub)" in season 1's history) -- the
substitute's result still counts for their groupmates' totals, but not
for the absent player's own personal count or total.

Reconciling GAMES_PLAYED against the schedule (``SEASON_2_SCHEDULE``) pod
by pod -- a pod counts as "played" once any of its members' personal game
count has advanced past it -- identifies exactly which pods are still
genuinely unplayed by everyone in them (``REMAINING_FIXTURES``) versus
already resolved via a substitute for whichever member's own count didn't
move (Will's November and Stu's November; Maclane's and Luke's October).
This fully reconciles: every player's (3 - games_played) gap is either
explained by a still-open fixture below, or by exactly one such
sub-covered round that won't recur. If more results come in, this file
is what to update -- move points from REMAINING_FIXTURES's resolution
into CURRENT_STANDINGS and drop the now-played pod from the list.
"""
from __future__ import annotations

STANDINGS_AS_OF = "2026-11-15"

# name -> (games personally played, cumulative total points)
CURRENT_STANDINGS: dict[str, tuple[int, int]] = {
    "Isaiah": (3, 1068),
    "Sam": (3, 989),
    "Kannon": (2, 809),
    "Jack": (2, 773),
    "Max": (3, 758),
    "Peter": (3, 753),
    "Jackson": (2, 593),
    "Stu": (2, 581),
    "Christian": (2, 479),
    "Cailin": (2, 394),
    "Will": (1, 390),
    "Ivan": (3, 321),
    "Harrison": (1, 237),
    "Jorgen": (1, 168),
    "Luke": (1, 128),
    "Maclane": (1, 79),
}

# Pods nobody in them has played yet -- the only fixtures left to
# project. (label, [4 player names])
REMAINING_FIXTURES: list[tuple[str, list[str]]] = [
    ("October Group 3", ["Christian", "Jorgen", "Harrison", "Will"]),
    ("November Group 1", ["Kannon", "Jackson", "Harrison", "Maclane"]),
    ("November Group 4", ["Jack", "Jorgen", "Cailin", "Luke"]),
]
