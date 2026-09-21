"""Command-line entry point.

    python -m beerio_kart.cli --sims 20000 --seed 42
    python -m beerio_kart.cli --config beerio_kart/config/players.yaml
    python -m beerio_kart.cli --verbose --seed 1
    python -m beerio_kart.cli --config beerio_kart/config/players_calibrated.yaml \\
        --matchup Kannon Sam Max Jorgen
"""
from __future__ import annotations

import argparse
import random

from .match import MatchConfig
from .matchup import estimate_matchup
from .models import Player
from .monte_carlo import PlayerStats, run_monte_carlo
from .roster import default_roster, load_roster
from .season import SeasonResult, run_season


def format_table(stats: dict[str, PlayerStats]) -> str:
    rows = sorted((s.as_row() for s in stats.values()), key=lambda r: -r["champion_pct"])
    header = f"{'Player':<12}{'Avg Pts':>9}{'Playoffs%':>11}{'Finals%':>9}{'Champ%':>8}"
    lines = [header, "-" * len(header)]
    for r in rows:
        lines.append(
            f"{r['name']:<12}{r['avg_points']:>9.1f}"
            f"{r['playoff_pct']:>10.1f}%{r['finals_pct']:>8.1f}%{r['champion_pct']:>7.1f}%"
        )
    return "\n".join(lines)


def print_season_detail(result: SeasonResult) -> None:
    print("=== League phase ===")
    for month, pods in result.league.monthly_results.items():
        print(f"{month}:")
        for pod_label, match in pods.items():
            ranked = match.ranked()
            scores = ", ".join(f"{pid} {match.points[pid]}" for pid in ranked)
            print(f"  {pod_label}: {scores}")

    print("\n=== Season standings (top 8 make playoffs) ===")
    ranked = sorted(result.league.season_points, key=lambda pid: -result.league.season_points[pid])
    for rank, pid in enumerate(ranked, start=1):
        tag = "  <- makes playoffs" if rank <= 8 else ""
        print(f"  {rank}. {pid:<10} {result.league.season_points[pid]:>5} pts{tag}")

    print("\n=== Playoffs ===")
    print("Seeds:", ", ".join(f"{i + 1}:{pid}" for i, pid in enumerate(result.playoffs.seeds)))
    print("Group [1,2,7,8] result:", result.playoffs.bracket_top.ranked())
    print("Group [3,4,5,6] result:", result.playoffs.bracket_bottom.ranked())
    print("Finalists:", result.playoffs.finalists)
    print("Final standings:", result.playoffs.final.ranked())
    print("\nCHAMPION:", result.playoffs.champion)


def format_matchup(players: list[Player], estimate) -> str:
    rows = sorted(players, key=lambda p: -estimate.avg_points[p.id])
    header = f"{'Player':<12}{'Skill':>8}{'Avg Points':>12}{'Win %':>8}"
    lines = [header, "-" * len(header)]
    for p in rows:
        lines.append(
            f"{p.name:<12}{p.skill:>8.1f}{estimate.avg_points[p.id]:>12.1f}"
            f"{estimate.win_pct[p.id]:>7.1f}%"
        )
    lines.append(f"\n({estimate.trials} simulated matches)")
    return "\n".join(lines)


def run_matchup(names: list[str], players: list[Player], config: MatchConfig, trials: int, rng) -> None:
    by_name = {p.name: p for p in players}
    if len(set(names)) != 4:
        raise SystemExit("--matchup needs 4 distinct player names")
    missing = [n for n in names if n not in by_name]
    if missing:
        available = ", ".join(sorted(by_name))
        raise SystemExit(f"Unknown player(s): {', '.join(missing)}\nAvailable: {available}")

    matchup_players = [by_name[n] for n in names]
    estimate = estimate_matchup(matchup_players, config, rng, trials=trials)
    print(f"Matchup: {' vs '.join(names)}\n")
    print(format_matchup(matchup_players, estimate))


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
    parser.add_argument(
        "--matchup",
        nargs=4,
        metavar=("PLAYER1", "PLAYER2", "PLAYER3", "PLAYER4"),
        help="estimate scores for a specific 4-player matchup instead of a full season",
    )
    parser.add_argument(
        "--matchup-trials", type=int, default=300, help="simulated matches to average for --matchup"
    )
    args = parser.parse_args()

    rng = random.Random(args.seed)
    players, schedule = load_roster(args.config) if args.config else default_roster()
    config = MatchConfig(
        beers_per_player=args.beers_per_player,
        impairment_coef=args.impairment_coef,
        chaos_scale=args.chaos_scale,
    )

    if args.matchup:
        run_matchup(args.matchup, players, config, args.matchup_trials, rng)
        return

    if args.verbose:
        print_season_detail(run_season(schedule, config, rng))
        return

    stats = run_monte_carlo(players, schedule, config, args.sims, rng)
    print(f"Ran {args.sims} simulated seasons\n")
    print(format_table(stats))


if __name__ == "__main__":
    main()
