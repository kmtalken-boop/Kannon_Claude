"""Fit skill ratings from real history and write a calibrated roster.

    python3 -m beerio_kart.build_roster_from_history

Reads ``data/history.py`` (transcribed from the league's Google Sheet),
fits Plackett-Luce strengths with ``calibrate.fit_plackett_luce``, and
writes ``config/players_calibrated.yaml`` with real skill ratings for the
12 known recurring drivers.

The real league described to build this simulator has 16 players in 4
fixed groups of 4; the historical sheet only has 12 drivers in 3 rotating
groups. This script fits what the data actually supports -- 12 skill
ratings -- and splits them into 3 groups of 4 by seeding (so groups are
roughly balanced) rather than guessing at a 16th-player roster. Swap in
the real 4x4 groups (and the missing 4 players' names/skills) by hand
once you have them; everything downstream just reads the YAML.
"""
from __future__ import annotations

import yaml

from .calibrate import fit_plackett_luce, strengths_to_skill
from .data.history import SEASON_TOTALS_THROUGH_WEEK_3, SUBSTITUTE_IDS, WEEKLY_GROUP_RESULTS


def build_calibrated_skills() -> dict[str, float]:
    strengths = fit_plackett_luce(WEEKLY_GROUP_RESULTS)
    skills = strengths_to_skill(strengths)
    return {pid: skill for pid, skill in skills.items() if pid not in SUBSTITUTE_IDS}


def snake_draft_groups(skills: dict[str, float], group_size: int = 4) -> dict[str, list[dict]]:
    """Split ranked players into balanced groups via a snake draft, so
    each group has a similar overall skill mix instead of one group being
    all the strongest players.
    """
    ranked = sorted(skills, key=lambda pid: -skills[pid])
    n_groups = -(-len(ranked) // group_size)  # ceil
    group_names = [chr(ord("A") + i) for i in range(n_groups)]
    groups: dict[str, list[str]] = {name: [] for name in group_names}

    pos = 0
    round_num = 0
    while pos < len(ranked):
        pick_order = group_names if round_num % 2 == 0 else list(reversed(group_names))
        for name in pick_order:
            if pos >= len(ranked):
                break
            groups[name].append(ranked[pos])
            pos += 1
        round_num += 1

    return {
        name: [{"name": pid, "skill": round(skills[pid], 1)} for pid in members]
        for name, members in groups.items()
    }


def main() -> None:
    skills = build_calibrated_skills()

    print("Calibrated skill ratings (Plackett-Luce fit, mean = 1000):")
    for pid in sorted(skills, key=lambda p: -skills[p]):
        sheet_total = SEASON_TOTALS_THROUGH_WEEK_3.get(pid, "?")
        print(f"  {pid:<10} skill={skills[pid]:>7.1f}   (sheet total through wk3: {sheet_total})")

    groups = snake_draft_groups(skills)
    out_path = "beerio_kart/config/players_calibrated.yaml"
    with open(out_path, "w") as f:
        f.write(
            "# Skill ratings fit from real historical results via a Plackett-Luce\n"
            "# MLE (see calibrate.py + build_roster_from_history.py). Only the 12\n"
            "# known recurring drivers are here -- this league needs 16 across 4\n"
            "# groups of 4, so 4 more players still need to be added by hand.\n"
        )
        yaml.dump({"groups": groups}, f, sort_keys=False)

    print(f"\nWrote {out_path} ({len(skills)} players in {len(groups)} groups)")


if __name__ == "__main__":
    main()
