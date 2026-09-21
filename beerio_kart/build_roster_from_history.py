"""Fit skill ratings from real history and write a calibrated roster.

    python3 -m beerio_kart.build_roster_from_history

Reads ``data/history.py`` (season 1's weekly results and playoffs, plus
season 2's first week), fits Plackett-Luce strengths across all of it with
``calibrate.fit_plackett_luce``, and writes
``config/players_calibrated.yaml``.

This season's real group assignments (``SEASON_2_GROUPS``) are used
directly for the 3 groups known so far, rather than re-drafting players
into artificial balanced groups -- group assignment is the league's call,
not this script's. The league's target structure is 16 players in 4 fixed
groups of 4; only 12 players/3 groups have been provided for this season,
so the YAML this writes is one group short until group D is known (for
players who aren't in ``SEASON_2_GROUPS`` at all -- e.g. anyone who played
last season but isn't confirmed for this one -- their fitted skill is
still printed below for reference, in case they end up in group D).
"""
from __future__ import annotations

import yaml

from .calibrate import fit_plackett_luce, strengths_to_skill
from .data.history import ALL_RANKING_EVENTS, SEASON_2_GROUPS, SUBSTITUTE_IDS


def build_calibrated_skills() -> dict[str, float]:
    strengths = fit_plackett_luce(ALL_RANKING_EVENTS)
    skills = strengths_to_skill(strengths)
    return {pid: skill for pid, skill in skills.items() if pid not in SUBSTITUTE_IDS}


def main() -> None:
    skills = build_calibrated_skills()

    print("Calibrated skill ratings (Plackett-Luce fit over all history, mean = 1000):")
    for pid in sorted(skills, key=lambda p: -skills[p]):
        print(f"  {pid:<10} skill={skills[pid]:>7.1f}")

    assigned = {pid for members in SEASON_2_GROUPS.values() for pid in members}
    unassigned = sorted((skills[pid], pid) for pid in skills if pid not in assigned)
    if unassigned:
        print("\nNot in a season-2 group yet (candidates for group D):")
        for skill, pid in reversed(unassigned):
            print(f"  {pid:<10} skill={skill:>7.1f}")

    groups = {
        name: [{"name": pid, "skill": round(skills[pid], 1)} for pid in members]
        for name, members in SEASON_2_GROUPS.items()
    }
    out_path = "beerio_kart/config/players_calibrated.yaml"
    with open(out_path, "w") as f:
        f.write(
            "# Skill ratings fit from real historical results via a Plackett-Luce\n"
            "# MLE (see calibrate.py + build_roster_from_history.py), placed into\n"
            "# this season's real groups (data/history.py: SEASON_2_GROUPS). Group D\n"
            "# is still missing -- this league needs 16 players across 4 groups of 4,\n"
            "# and only 3 groups (12 players) have been confirmed for this season.\n"
        )
        yaml.dump({"groups": groups}, f, sort_keys=False)

    print(f"\nWrote {out_path} ({sum(len(g) for g in groups.values())} players in {len(groups)} groups)")


if __name__ == "__main__":
    main()
