"""Kannon — Kalshi market making bot entry point."""
from __future__ import annotations
import asyncio
import logging
import os
import signal
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml
from dotenv import load_dotenv
from rich.console import Console
from rich.logging import RichHandler
from rich.table import Table

from .api.auth import KalshiAuth
from .api.client import KalshiClient
from .api.feed import OrderbookFeed
from .api.models import Orderbook
from .execution.order_manager import OrderManager
from .risk.risk_manager import RiskManager
from .strategy.fair_value import FairValueModel
from .strategy.market_maker import MarketMakerStrategy
from .strategy.screener import MarketScreener

console = Console()
logger = logging.getLogger(__name__)


def setup_logging(level: str, log_file: str | None):
    Path("logs").mkdir(exist_ok=True)
    handlers: list[logging.Handler] = [
        RichHandler(console=console, rich_tracebacks=True, markup=True)
    ]
    if log_file:
        handlers.append(logging.FileHandler(log_file))
    logging.basicConfig(level=level.upper(), format="%(message)s", handlers=handlers)


def load_config() -> dict:
    path = Path("config.yaml")
    if not path.exists():
        console.print("[red]config.yaml not found — run from the project root.[/red]")
        sys.exit(1)
    with open(path) as fh:
        return yaml.safe_load(fh)


class KalshiBot:
    def __init__(self, cfg: dict):
        self._cfg = cfg
        self._screener = MarketScreener(cfg["screening"])
        self._fv_model = FairValueModel(cfg.get("fair_value", {}))
        self._mm = MarketMakerStrategy(cfg["market_making"])
        self._risk = RiskManager(cfg["risk"])
        self._positions: dict[str, int] = {}
        self._active_tickers: list[str] = []
        self._running = False
        # Set during run()
        self._client: KalshiClient | None = None
        self._feed: OrderbookFeed | None = None
        self._orders: OrderManager | None = None

    # ── Callbacks ─────────────────────────────────────────────────────────────

    async def _on_orderbook(self, ob: Orderbook):
        if not self._risk.enabled:
            return
        fv = self._fv_model.compute(ob)
        if fv is None:
            return

        position = self._positions.get(ob.ticker, 0)
        time_remaining = self._time_remaining(ob.ticker)

        quote = self._mm.compute_quote(
            ticker=ob.ticker,
            fair_value=fv.fair_value,
            position=position,
            volatility=fv.volatility,
            confidence=fv.confidence,
            time_remaining=time_remaining,
        )
        if quote:
            await self._orders.update(quote)

    def _time_remaining(self, ticker: str) -> float:
        """Normalized time remaining in [0,1]. Falls back to 1.0 if unknown."""
        # Will be populated once market metadata is stored; for now return 1.0
        return 1.0

    # ── Loops ─────────────────────────────────────────────────────────────────

    async def _market_refresh_loop(self):
        interval = self._cfg["screening"].get("market_refresh_interval_seconds", 300)
        while self._running:
            try:
                await self._refresh_markets()
            except Exception as exc:
                logger.error(f"Market refresh error: {exc}", exc_info=True)
            await asyncio.sleep(interval)

    async def _position_sync_loop(self):
        interval = self._cfg["market_making"].get("position_sync_interval_seconds", 30)
        while self._running:
            await asyncio.sleep(interval)
            try:
                await self._sync_positions()
            except Exception as exc:
                logger.error(f"Position sync error: {exc}", exc_info=True)

            risk = self._risk.summary()
            if not risk["enabled"]:
                logger.warning(f"[bold red]HALTED[/bold red]: {risk['halt_reason']}")
                await self._orders.cancel_all()

    async def _stale_order_loop(self):
        ttl = self._cfg["market_making"].get("stale_quote_ttl_seconds", 30)
        while self._running:
            await asyncio.sleep(ttl)
            try:
                await self._orders.cancel_stale()
            except Exception as exc:
                logger.error(f"Stale order cleanup error: {exc}", exc_info=True)

    # ── Helpers ───────────────────────────────────────────────────────────────

    async def _refresh_markets(self):
        all_markets = await self._client.get_all_open_markets()
        selected = self._screener.select(all_markets)
        new_tickers = [m.ticker for m in selected]

        old = set(self._active_tickers)
        new = set(new_tickers)

        to_drop = old - new
        to_add = new - old

        if to_drop:
            for t in to_drop:
                await self._orders.cancel_ticker(t)
            await self._feed.unsubscribe(list(to_drop))

        if to_add:
            await self._feed.subscribe(list(to_add))

        self._active_tickers = new_tickers
        self._print_market_table(selected)

    async def _sync_positions(self):
        positions = await self._client.get_positions()
        self._positions = {p.ticker: p.market_exposure for p in positions}
        self._risk.update_delta(self._positions)
        balance = await self._client.get_balance()
        logger.info(
            f"Balance: ${balance.balance_dollars:.2f} | "
            f"Positions: {len(self._positions)} markets | "
            f"Daily P&L: ${self._risk.status.daily_pnl:.2f}"
        )

    def _print_market_table(self, markets):
        table = Table(title=f"Active Markets ({len(markets)})", show_lines=False)
        table.add_column("Ticker", style="cyan")
        table.add_column("Bid", justify="right")
        table.add_column("Ask", justify="right")
        table.add_column("Mid", justify="right")
        table.add_column("Vol 24h", justify="right")
        table.add_column("OI", justify="right")
        for m in markets:
            bid = f"{m.yes_bid}¢" if m.yes_bid else "-"
            ask = f"{m.yes_ask}¢" if m.yes_ask else "-"
            mid = f"{m.mid_price:.1f}¢" if m.mid_price else "-"
            table.add_row(m.ticker, bid, ask, mid, str(m.volume_24h), str(m.open_interest))
        console.print(table)

    # ── Entry point ───────────────────────────────────────────────────────────

    async def run(self):
        kcfg = self._cfg["kalshi"]
        env = kcfg["environment"].upper()
        console.rule(f"[bold green]Kannon Market Maker — {env}[/bold green]")

        api_key_id = os.environ["KALSHI_API_KEY_ID"]
        key_path = os.environ["KALSHI_PRIVATE_KEY_PATH"]
        auth = KalshiAuth(api_key_id, key_path)

        async with KalshiClient(
            base_url=kcfg["base_url"],
            auth=auth,
            rate_limit_rps=kcfg.get("rate_limit_rps", 10),
        ) as client:
            self._client = client
            self._orders = OrderManager(
                client,
                stale_ttl_seconds=self._cfg["market_making"].get("stale_quote_ttl_seconds", 30),
            )
            self._feed = OrderbookFeed(ws_url=kcfg["ws_url"], auth=auth)
            self._feed.on_update(self._on_orderbook)
            self._running = True

            await self._refresh_markets()
            await self._sync_positions()

            await asyncio.gather(
                self._feed.run(),
                self._market_refresh_loop(),
                self._position_sync_loop(),
                self._stale_order_loop(),
            )

    async def shutdown(self):
        self._running = False
        if self._feed:
            self._feed.stop()
        if self._orders:
            console.print("[yellow]Cancelling all resting orders...[/yellow]")
            await self._orders.cancel_all()
        console.print("[green]Shutdown complete.[/green]")


def main():
    load_dotenv()
    cfg = load_config()
    log_cfg = cfg.get("logging", {})
    setup_logging(log_cfg.get("level", "INFO"), log_cfg.get("file"))

    bot = KalshiBot(cfg)
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    def _handle_signal(sig, _frame):
        console.print(f"\n[yellow]Signal {sig.name} received, shutting down...[/yellow]")
        loop.create_task(bot.shutdown())
        loop.call_later(8, loop.stop)

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    try:
        loop.run_until_complete(bot.run())
    finally:
        loop.close()


if __name__ == "__main__":
    main()
