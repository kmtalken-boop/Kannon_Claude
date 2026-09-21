"""Core data types shared across the simulator."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Player:
    id: str
    name: str
    skill: float = 1000.0


@dataclass
class MatchResult:
    """Result of one 32-race match between a fixed set of players."""

    points: dict[str, int]
    race_wins: dict[str, int]
    peak_impairment: dict[str, float]

    def ranked(self) -> list[str]:
        """Player ids ordered best (most points) to worst.

        Ties are broken by race wins (1st-place finishes) within the match,
        since raw points alone can tie.
        """
        return sorted(self.points, key=lambda pid: (-self.points[pid], -self.race_wins[pid]))
