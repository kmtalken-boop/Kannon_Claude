"""The league's real current standings, as reported directly by the user
(a screenshot of the standings table), as of 2026-11-15.

Unlike ``SEASON_2_KNOWN_RESULTS`` (per-match points for specific pods),
this is each player's *cumulative* season total plus how many of their 3
scheduled matches they've personally played. Games-played isn't uniform
across players because pods complete at different paces: Will's banked
390 is actually his *November* result (he hadn't played September or
October yet, despite being on the original September Group 4 roster),
and Stu's 581 is his October+November total with September still open --
both confirmed directly by the user after an initial reconciliation
attempt (which assumed September Group 4 had already happened) came out
wrong. With that fixed, every player's (3 - games_played) gap matches the
number of pods below they still appear in exactly -- see
tests/test_current_projection.py's reconciliation check. If more results
come in, this file is what to update -- move points from
REMAINING_FIXTURES's resolution into CURRENT_STANDINGS and drop the
now-played pod from the list.
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
    ("September Group 4", ["Luke", "Maclane", "Will", "Stu"]),
    ("October Group 3", ["Christian", "Jorgen", "Harrison", "Will"]),
    ("November Group 1", ["Kannon", "Jackson", "Harrison", "Maclane"]),
    ("November Group 4", ["Jack", "Jorgen", "Cailin", "Luke"]),
]

# All 16 players ranked by this season's real points-per-game (not raw
# total, which would unfairly reward/punish players for how many games
# they've happened to play so far). Fed into the Plackett-Luce fit
# (calibrate.py via data/history.py) as a ranking event in its own right,
# alongside the older SEASON_2_EXPERT_RANKING -- this is what lets actual
# in-season form (e.g. Isaiah leading the league in points, well ahead of
# where the preseason expert ranking placed him relative to Sam) pull a
# player's fitted skill toward what they're actually doing now, rather
# than staying anchored to a snapshot taken before most of these games
# were played.
SEASON_2_CURRENT_FORM_RANKING: list[str] = sorted(
    CURRENT_STANDINGS, key=lambda name: -(CURRENT_STANDINGS[name][1] / CURRENT_STANDINGS[name][0])
)

