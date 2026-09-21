"""Fit skill ratings from real history and write a calibrated roster.

    python3 -m beerio_kart.build_roster_from_history

Reads ``data/history.py`` (season 1's weekly results and playoffs, plus
season 2's first week), fits Plackett-Luce strengths across all of it with
``calibrate.fit_plackett_luce``, layers on ``MANUAL_SKILL_ESTIMATES`` for
drivers with no race history yet, and writes
``config/players_calibrated.yaml`` using this season's real 4x4 group
assignments (``SEASON_2_GROUPS``) -- group assignment is the league's
call, not this script's, so it's never re-drafted or rebalanced here.
"""
from __future__ import annotations

import yaml

from .calibrate import fit_plackett_luce, strengths_to_skill
from .data.history import (
    ALL_RANKING_EVENTS,
    ALL_RANKING_WEIGHTS,
    FORM_ADJUSTMENTS,
    MANUAL_SKILL_ESTIMATES,
    SEASON_2_GROUPS,
    SUBSTITUTE_IDS,
)


def build_calibrated_skills() -> dict[str, float]:
    strengths = fit_plackett_luce(ALL_RANKING_EVENTS, weights=ALL_RANKING_WEIGHTS)
    skills = strengths_to_skill(strengths)
    skills = {pid: skill for pid, skill in skills.items() if pid not in SUBSTITUTE_IDS}
    for pid, multiplier in FORM_ADJUSTMENTS.items():
        skills[pid] = skills[pid] * multiplier
    skills.update(MANUAL_SKILL_ESTIMATES)
    return skills


def main() -> None:
    skills = build_calibrated_skills()
    rostered = {pid for members in SEASON_2_GROUPS.values() for pid in members}

    print("Calibrated skill ratings (Plackett-Luce fit + adjustments, mean ~1000 before adjustments):")
    for pid in sorted(skills, key=lambda p: -skills[p]):
        tag = "" if pid in rostered else "  (not in a season-2 group)"
        if pid in MANUAL_SKILL_ESTIMATES:
            source = " *manual estimate, no history*"
        elif pid in FORM_ADJUSTMENTS:
            source = f" *form-adjusted x{FORM_ADJUSTMENTS[pid]}*"
        else:
            source = ""
        print(f"  {pid:<10} skill={skills[pid]:>7.1f}{source}{tag}")

    missing = [pid for members in SEASON_2_GROUPS.values() for pid in members if pid not in skills]
    if missing:
        raise SystemExit(f"No skill available for rostered player(s): {missing}")

    groups = {
        name: [{"name": pid, "skill": round(skills[pid], 1)} for pid in members]
        for name, members in SEASON_2_GROUPS.items()
    }
    out_path = "beerio_kart/config/players_calibrated.yaml"
    with open(out_path, "w") as f:
        f.write(
            "# Skill ratings fit from real historical results via a recency-weighted\n"
            "# Plackett-Luce MLE (see calibrate.py + build_roster_from_history.py),\n"
            "# placed into this season's real groups (data/history.py: SEASON_2_GROUPS).\n"
            "# Maclane and Luke have no race history yet, so their skill is a manual\n"
            "# estimate (MANUAL_SKILL_ESTIMATES) -- replace it once they've actually\n"
            "# raced. Max's fitted skill is multiplied by a manual form adjustment\n"
            "# (FORM_ADJUSTMENTS) reflecting the league's read that he's improved\n"
            "# beyond what his single season-2 result shows.\n"
        )
        yaml.dump({"groups": groups}, f, sort_keys=False)

    print(f"\nWrote {out_path} ({sum(len(g) for g in groups.values())} players in {len(groups)} groups)")


if __name__ == "__main__":
    main()
