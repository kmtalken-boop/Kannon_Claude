"""Fit skill ratings from real history and write a calibrated roster.

    python3 -m beerio_kart.build_roster_from_history

Reads ``data/history.py`` (season 1's weekly results and playoffs, season
2's first week, and the league's own full-roster ranking), fits
Plackett-Luce strengths across all of it with
``calibrate.fit_plackett_luce``, layers on ``MANUAL_SKILL_ESTIMATES`` for
any driver still without race history, and writes
``config/players_calibrated.yaml``: a flat ``players:`` list plus the
real monthly ``schedule:`` (``data/schedule.py``: ``SEASON_2_SCHEDULE``).
"""
from __future__ import annotations

from dataclasses import dataclass

import yaml

from .calibrate import fit_plackett_luce, strengths_to_skill
from .data.history import (
    ALL_RANKING_EVENTS,
    ALL_RANKING_WEIGHTS,
    FORM_ADJUSTMENTS,
    MANUAL_SKILL_ESTIMATES,
    SUBSTITUTE_IDS,
)
from .data.schedule import SEASON_2_ROSTER, SEASON_2_SCHEDULE


@dataclass
class SkillBreakdown:
    fitted: float | None  # Plackett-Luce fit, pre-adjustment; None if no history
    multiplier: float  # FORM_ADJUSTMENTS factor, 1.0 if none applies
    manual_override: float | None  # MANUAL_SKILL_ESTIMATES value, if any
    effective: float  # what actually goes into config YAML / the simulator


def build_skill_breakdown() -> dict[str, SkillBreakdown]:
    strengths = fit_plackett_luce(ALL_RANKING_EVENTS, weights=ALL_RANKING_WEIGHTS)
    fitted = strengths_to_skill(strengths)
    fitted = {pid: skill for pid, skill in fitted.items() if pid not in SUBSTITUTE_IDS}

    all_ids = set(fitted) | set(MANUAL_SKILL_ESTIMATES)
    breakdown: dict[str, SkillBreakdown] = {}
    for pid in all_ids:
        manual = MANUAL_SKILL_ESTIMATES.get(pid)
        multiplier = FORM_ADJUSTMENTS.get(pid, 1.0)
        if manual is not None:
            effective = manual
        else:
            effective = fitted[pid] * multiplier
        breakdown[pid] = SkillBreakdown(
            fitted=fitted.get(pid), multiplier=multiplier, manual_override=manual, effective=effective
        )
    return breakdown


def build_calibrated_skills() -> dict[str, float]:
    return {pid: b.effective for pid, b in build_skill_breakdown().items()}


def main() -> None:
    skills = build_calibrated_skills()

    print("Calibrated skill ratings (Plackett-Luce fit + adjustments, mean ~1000 before adjustments):")
    for pid in sorted(skills, key=lambda p: -skills[p]):
        tag = "" if pid in SEASON_2_ROSTER else "  (not on this season's roster)"
        if pid in MANUAL_SKILL_ESTIMATES:
            source = " *manual estimate, no history*"
        elif pid in FORM_ADJUSTMENTS:
            source = f" *form-adjusted x{FORM_ADJUSTMENTS[pid]}*"
        else:
            source = ""
        print(f"  {pid:<10} skill={skills[pid]:>7.1f}{source}{tag}")

    missing = [pid for pid in SEASON_2_ROSTER if pid not in skills]
    if missing:
        raise SystemExit(f"No skill available for rostered player(s): {missing}")

    players = [{"name": pid, "skill": round(skills[pid], 1)} for pid in SEASON_2_ROSTER]
    out_path = "beerio_kart/config/players_calibrated.yaml"
    with open(out_path, "w") as f:
        f.write(
            "# Skill ratings fit from real historical results (season 1 weeks/playoffs,\n"
            "# season 2 week 1, and the league's own full-roster ranking) via a\n"
            "# recency-weighted Plackett-Luce MLE -- see calibrate.py and\n"
            "# build_roster_from_history.py. The schedule below is this season's real\n"
            "# monthly rotation (data/schedule.py: SEASON_2_SCHEDULE).\n"
        )
        yaml.dump({"players": players, "schedule": SEASON_2_SCHEDULE}, f, sort_keys=False)

    print(f"\nWrote {out_path} ({len(players)} players, {len(SEASON_2_SCHEDULE)}-month schedule)")


if __name__ == "__main__":
    main()
