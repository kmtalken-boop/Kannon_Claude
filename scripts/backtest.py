#!/usr/bin/env python3
"""
Kannon backtest — replay historical Kalshi trades against the MM strategy.

Usage:
    python scripts/backtest.py [--days N] [--markets N] [--clear-cache]

Options:
    --days N        How many days back to look for settled markets (default: 60)
    --markets N     Max number of markets to backtest (default: 50)
    --clear-cache   Delete cached data and re-download everything
    --min-trades N  Skip markets with fewer than N trades (default: 30)
"""
from __future__ import annotations
import argparse
import asyncio
import logging
import os
import shutil
import sys
from pathlib import Path

# Allow running from the repo root
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
import yaml
from rich.console import Console
from rich.progress import track

from kannon.api.auth import KalshiAuth
from kannon.api.client import KalshiClient
from kannon.backtest.data import HistoricalDataLoader, CACHE_DIR
from kannon.backtest.engine import BacktestEngine
from kannon.backtest.metrics import compute_summary
from kannon.backtest.report import print_market_table, print_summary, print_caveats
from kannon.strategy.fees import FeeConfig
from kannon.strategy.market_maker import MarketMakerStrategy

console = Console()
logging.basicConfig(level=logging.WARNING)  # quiet for backtest CLI


def load_config() -> dict:
    with open("config.yaml") as fh:
        return yaml.safe_load(fh)


async def run_backtest(args: argparse.Namespace):
    if args.clear_cache and CACHE_DIR.exists():
        shutil.rmtree(CACHE_DIR)
        console.print("[yellow]Cache cleared.[/yellow]")

    cfg = load_config()
    fee_cfg = FeeConfig(**cfg.get("fees", {}))
    mm_cfg = cfg["market_making"]

    # Use slightly wider params for backtest (no live book → less confidence)
    backtest_mm_cfg = {**mm_cfg, "target_half_spread_cents": 3.0, "min_half_spread_cents": 2.0}
    mm = MarketMakerStrategy(backtest_mm_cfg, fee_cfg=fee_cfg)
    engine = BacktestEngine(mm, fee_cfg)

    api_key_id = os.environ["KALSHI_API_KEY_ID"]
    key_path = os.environ["KALSHI_PRIVATE_KEY_PATH"]
    auth = KalshiAuth(api_key_id, key_path)

    console.rule("[bold green]Kannon Backtester[/bold green]")
    console.print(
        f"  Fee rate: [cyan]{fee_cfg.fee_rate*100:.0f}%[/cyan]  |  "
        f"Tax rate: [cyan]{fee_cfg.marginal_tax_rate*100:.0f}%[/cyan]  |  "
        f"Days back: [cyan]{args.days}[/cyan]  |  "
        f"Max markets: [cyan]{args.markets}[/cyan]\n"
    )

    async with KalshiClient(
        base_url=cfg["kalshi"]["base_url"],
        auth=auth,
        rate_limit_rps=cfg["kalshi"].get("rate_limit_rps", 10),
    ) as client:
        loader = HistoricalDataLoader(client)

        # Step 1: fetch settled markets
        with console.status("Fetching settled markets..."):
            markets = await loader.fetch_settled_markets(
                days_back=args.days, max_markets=args.markets
            )

        console.print(f"Found [cyan]{len(markets)}[/cyan] settled markets with results.\n")

        if not markets:
            console.print("[red]No settled markets found. Try increasing --days.[/red]")
            return

        # Step 2: fetch trade histories
        with console.status(f"Downloading trade histories (cached after first run)..."):
            all_trades = await loader.fetch_all_trades(markets, concurrency=5)

        # Step 3: simulate each market
        results = []
        skipped = 0

        for market in track(markets, description="Simulating markets..."):
            trades = all_trades.get(market.ticker, [])

            if len(trades) < args.min_trades:
                skipped += 1
                continue

            result = engine.simulate_market(
                ticker=market.ticker,
                trades=trades,
                resolution=market.result,
                last_price_cents=market.last_price or 50,
            )

            if result:
                results.append(result)

        # Count synthetic markets (trade IDs start with "syn-")
        synthetic_count = sum(
            1 for t_list in all_trades.values()
            if t_list and t_list[0].trade_id.startswith("syn-")
        )
        if synthetic_count:
            console.print(
                f"[yellow]Note: {synthetic_count} of {len(markets)} markets used synthetic "
                "trade data (demo API has no trade history for quick-settle markets).[/yellow]"
            )

        if skipped:
            console.print(f"[dim]Skipped {skipped} markets with < {args.min_trades} trades.[/dim]")

        if not results:
            console.print("[red]No results — all markets had too few trades.[/red]")
            return

    # Step 4: report
    console.print()
    print_market_table(results)
    console.print()
    summary = compute_summary(results)
    print_summary(summary)
    print_caveats()


def main():
    load_dotenv()
    parser = argparse.ArgumentParser(description="Kannon backtest")
    parser.add_argument("--days", type=int, default=60,
                        help="Days back to look for settled markets (default: 60)")
    parser.add_argument("--markets", type=int, default=50,
                        help="Max number of markets to backtest (default: 50)")
    parser.add_argument("--min-trades", type=int, default=30,
                        help="Skip markets with fewer than N trades (default: 30)")
    parser.add_argument("--clear-cache", action="store_true",
                        help="Delete cached data and re-download")
    args = parser.parse_args()
    asyncio.run(run_backtest(args))


if __name__ == "__main__":
    main()
