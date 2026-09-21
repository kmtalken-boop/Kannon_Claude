"""The real monthly schedule: who plays whom, month by month.

Groups are NOT fixed for the season -- they're redrawn every month, and
each of the 16 players faces a different set of 3 opponents each month.
"Total points over your 3 placement matches" (the playoff-qualification
rule) is therefore just each player's own points summed across their 3
different monthly matches, and the top 8 of all 16 by that total make the
playoffs directly -- there's no "top 2 from each group" step, since no
group persists long enough to have its own standings.

September's real results are already in ``history.py`` (that's
``SEASON_2_WEEK_1_RESULTS`` -- same 3 pods, just given in a different
name order there). October and November haven't been played yet; the
season simulator plays all 3 months from the fitted skills, September
included, rather than mixing known results with simulated ones -- a
deliberate simplification (the fit already leans on the real September
results through SEASON_2_RECENCY_WEIGHT) to keep one simulation
mechanism for the whole season instead of two.
"""
from __future__ import annotations

from ..models import Player

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
