"""Command-line entry point.

    python -m beerio_kart.cli --sims 20000 --seed 42
    python -m beerio_kart.cli --config beerio_kart/config/players.yaml
    python -m beerio_kart.cli --verbose --seed 1
"""
from __future__ import annotations

import argparse
import random

from .match import MatchConfig
from .monte_carlo import PlayerStats, run_monte_carlo
from .roster import default_roster, load_roster
from .season import SeasonResult, run_season


def format_table(stats: dict[str, PlayerStats]) -> str:
    rows = sorted((s.as_row() for s in stats.values()), key=lambda r: -r["champion_pct"])
    header = f"{'Player':<10}{'Grp':<5}{'Avg Pts':>9}{'Playoffs%':>11}{'Finals%':>9}{'Champ%':>8}"
    lines = [header, "-" * len(header)]
    for r in rows:
        lines.append(
            f"{r['name']:<10}{r['group']:<5}{r['avg_points']:>9.1f}"
            f"{r['playoff_pct']:>10.1f}%{r['finals_pct']:>8.1f}%{r['champion_pct']:>7.1f}%"
        )
    return "\n".join(lines)


def print_season_detail(result: SeasonResult) -> None:
    print("=== League phase ===")
    for name, group in result.groups.items():
        print(f"Group {name}:")
        for rank, pid in enumerate(group.standings(), start=1):
            tag = "  <- advances" if rank <= 2 else ""
            print(f"  {rank}. {pid:<10} {group.season_points[pid]:>4} pts{tag}")

    print("\n=== Playoffs ===")
    print("Seeds:", ", ".join(f"{i + 1}:{pid}" for i, pid in enumerate(result.playoffs.seeds)))
    print("Group [1,2,7,8] result:", result.playoffs.bracket_top.ranked())
    print("Group [3,4,5,6] result:", result.playoffs.bracket_bottom.ranked())
    print("Finalists:", result.playoffs.finalists)
    print("Final standings:", result.playoffs.final.ranked())
    print("\nCHAMPION:", result.playoffs.champion)


def main() -> None:
    parser = argparse.ArgumentParser(description="Beerio Kart league predictor")
    parser.add_argument("--config", help="YAML roster file (default: built-in equal-skill roster)")
    parser.add_argument("--sims", type=int, default=10000, help="number of simulated seasons")
    parser.add_argument("--seed", type=int, default=None, help="RNG seed for reproducibility")
    parser.add_argument(
        "--verbose", action="store_true", help="print one detailed season instead of a Monte Carlo table"
    )
    parser.add_argument("--beers-per-player", type=int, default=8)
    parser.add_argument(
        "--impairment-coef", type=float, default=0.12, help="how hard accumulated beers hit effective skill"
    )
    parser.add_argument(
        "--chaos-scale", type=float, default=1.0, help="in-game randomness; higher flattens skill gaps"
    )
    args = parser.parse_args()

    rng = random.Random(args.seed)
    groups = load_roster(args.config) if args.config else default_roster()
    config = MatchConfig(
        beers_per_player=args.beers_per_player,
        impairment_coef=args.impairment_coef,
        chaos_scale=args.chaos_scale,
    )

    if args.verbose:
        print_season_detail(run_season(groups, config, rng))
        return

    stats = run_monte_carlo(groups, config, args.sims, rng)
    print(f"Ran {args.sims} simulated seasons\n")
    print(format_table(stats))


if __name__ == "__main__":
    main()
