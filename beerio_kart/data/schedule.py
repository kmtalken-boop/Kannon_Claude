"""The real monthly schedule: who plays whom, month by month.

Groups are NOT fixed for the season -- they're redrawn every month, and
each of the 16 players faces a different set of 3 opponents each month.
"Total points over your 3 placement matches" (the playoff-qualification
rule) is therefore just each player's own points summed across their 3
different monthly matches, and the top 8 of all 16 by that total make the
playoffs directly -- there's no "top 2 from each group" step, since no
group persists long enough to have its own standings.

September's real results are already known for 3 of its 4 pods (see
``SEASON_2_KNOWN_RESULTS`` below, sourced from ``history_points.py``'s
``SEASON_2_WEEK_1_POINTS``) -- the season simulator uses those actual
points directly instead of simulating that pod, and only simulates from
the fitted skills where the real result isn't known yet (September's
Group 4, and all of October/November). October and November haven't
been played yet.
"""
from __future__ import annotations

from ..models import Player
from .history_points import SEASON_2_WEEK_1_POINTS

def _roster_from(schedule: dict[str, dict[str, list[str]]]) -> list[str]:
    """The 16 distinct names in a schedule, in first-appearance order."""
    seen: list[str] = []
    for pods in schedule.values():
        for names in pods.values():
            for name in names:
                if name not in seen:
                    seen.append(name)
    return seen


SEASON_2_SCHEDULE: dict[str, dict[str, list[str]]] = {
    "September": {
        "Group 1": ["Kannon", "Peter", "Christian", "Jack"],
        "Group 2": ["Sam", "Max", "Jorgen", "Jackson"],
        "Group 3": ["Isaiah", "Cailin", "Harrison", "Ivan"],
        "Group 4": ["Luke", "Maclane", "Will", "Stu"],
    },
    "October": {
        "Group 1": ["Kannon", "Sam", "Isaiah", "Luke"],
        "Group 2": ["Peter", "Max", "Cailin", "Maclane"],
        "Group 3": ["Christian", "Jorgen", "Harrison", "Will"],
        "Group 4": ["Jack", "Jackson", "Ivan", "Stu"],
    },
    "November": {
        "Group 1": ["Kannon", "Jackson", "Harrison", "Maclane"],
        "Group 2": ["Peter", "Sam", "Ivan", "Will"],
        "Group 3": ["Christian", "Max", "Isaiah", "Stu"],
        "Group 4": ["Jack", "Jorgen", "Cailin", "Luke"],
    },
}

# The 16 rostered players' names, in the order they first appear in the
# schedule above -- the single source of truth for "who's on the roster
# this season" (rather than a separately maintained list that could drift
# from the schedule itself).
SEASON_2_ROSTER: list[str] = _roster_from(SEASON_2_SCHEDULE)

# The same schedule's *shape* -- which of 16 generic slots share a pod
# each month -- with names replaced by position (0 = first name to appear
# in September, in reading order). Reused by default_schedule() so a
# generic/example roster still gets a real, validated (nobody repeats an
# opponent) 3-month rotation instead of a made-up one.
_SCHEDULE_SHAPE: dict[str, dict[str, list[int]]] = {
    "September": {"Group 1": [0, 1, 2, 3], "Group 2": [4, 5, 6, 7], "Group 3": [8, 9, 10, 11], "Group 4": [12, 13, 14, 15]},
    "October": {"Group 1": [0, 4, 8, 12], "Group 2": [1, 5, 9, 13], "Group 3": [2, 6, 10, 14], "Group 4": [3, 7, 11, 15]},
    "November": {"Group 1": [0, 7, 10, 13], "Group 2": [1, 4, 11, 14], "Group 3": [2, 5, 8, 15], "Group 4": [3, 6, 9, 12]},
}


def build_schedule(players_by_name: dict[str, Player], schedule: dict[str, dict[str, list[str]]]) -> dict[str, dict[str, list[Player]]]:
    """Resolve a name-based schedule (like SEASON_2_SCHEDULE) into Players."""
    return {
        month: {label: [players_by_name[name] for name in names] for label, names in pods.items()}
        for month, pods in schedule.items()
    }


def default_schedule(players: list[Player]) -> dict[str, dict[str, list[Player]]]:
    """A generic, validated 3-month/4-pod rotation for exactly 16 players,
    in the order given -- reuses SEASON_2_SCHEDULE's shape (every pair of
    players shares a pod at most once) rather than inventing a new one.
    """
    if len(players) != 16:
        raise ValueError(f"default_schedule needs exactly 16 players, got {len(players)}")
    return {
        month: {label: [players[i] for i in idxs] for label, idxs in pods.items()}
        for month, pods in _SCHEDULE_SHAPE.items()
    }


# Real recorded results, by month, as a list of {player name: points} maps
# (one per pod that's actually been played). league.py matches these onto
# the schedule by player-id set, not by pod label, so this works regardless
# of how a roster labels its pods -- and simply doesn't match (falls back
# to simulating) for any custom roster whose names aren't these exact 16.
# September's Group 4 (Will, Stu, Maclane, Luke) isn't here because it was
# never on the original tracking sheet -- it's still simulated.
SEASON_2_KNOWN_RESULTS: dict[str, list[dict[str, int]]] = {
    "September": [dict(results) for _label, results in SEASON_2_WEEK_1_POINTS],
}
