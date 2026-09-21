"""Regular-season (league) phase.

Groups are redrawn every month -- see ``data/schedule.py`` -- so there's
no persistent "group" a player accumulates standings within. Each
player's season total is just their own points summed across their 3
different monthly matches (their "3 placement matches"), against 3
different sets of opponents.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field

from .match import MatchConfig, MatchResult, simulate_match
from .models import Player


@dataclass
class LeagueResult:
    season_points: dict[str, int] = field(default_factory=dict)
    monthly_results: dict[str, dict[str, MatchResult]] = field(default_factory=dict)
    # (month, pod_label) pairs whose result came from known_results (a real
    # recorded match) rather than simulate_match.
    known_pods: set[tuple[str, str]] = field(default_factory=set)


def run_league_phase(
    schedule: dict[str, dict[str, list[Player]]],
    config: MatchConfig,
    rng: random.Random,
    known_results: dict[str, list[dict[str, int]]] | None = None,
) -> LeagueResult:
    """``known_results``: real recorded points for pods that have actually
    been played, e.g. ``data/schedule.py``'s ``SEASON_2_KNOWN_RESULTS``.
    Matched onto the schedule by player-id set (not by month/pod label),
    so a pod is only replaced with its real result when every one of its
    4 players' ids exactly matches a known result -- anything else (a
    pod that hasn't been played yet, or a custom roster whose names don't
    match) is simulated as usual.
    """
    known_results = known_results or {}
    result = LeagueResult()
    for month, pods in schedule.items():
        month_known = known_results.get(month, [])
        result.monthly_results[month] = {}
        for pod_label, players in pods.items():
            if len(players) != 4:
                raise ValueError(f"{month} {pod_label} must have exactly 4 players")
            player_ids = {p.id for p in players}
            known = next((k for k in month_known if set(k) == player_ids), None)
            if known is not None:
                match = MatchResult(
                    points=dict(known),
                    race_wins={pid: 0 for pid in known},
                    peak_impairment={pid: 0.0 for pid in known},
                )
                result.known_pods.add((month, pod_label))
            else:
                match = simulate_match(players, config, rng)
            result.monthly_results[month][pod_label] = match
            for pid, pts in match.points.items():
                result.season_points[pid] = result.season_points.get(pid, 0) + pts
    return result
