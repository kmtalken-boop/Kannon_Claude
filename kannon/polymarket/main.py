"""Kannon — Polymarket US market making bot entry point."""
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

from .auth import PolymarketAuth
from .client import PolymarketClient
from .feed import PolymarketFeed
from .models import PMMarketState
from .order_manager import PolymarketOrderManager
from ..api.feed import TradeEvent
from ..api.models import Orderbook
from ..risk.risk_manager import RiskManager
from ..strategy.fair_value import FairValueModel
from ..strategy.fees import FeeConfig, EVCalculator
from ..strategy.market_maker import MarketMakerStrategy
from ..strategy.ofi import OFITracker
from ..strategy.screener import MarketScreener
from ..strategy.vpin import VPINTracker, FlowRegime

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


class PolymarketBot:
    def __init__(self, cfg: dict):
        self._cfg = cfg

        # Makers pay 0% on Polymarket — fee model reflects actual economics
        pm_fee_cfg = FeeConfig(
            fee_rate=0.0,
            marginal_tax_rate=cfg.get("fees", {}).get("marginal_tax_rate", 0.0),
            flat_fee_cents=0.0,
        )
        self._fee_cfg = pm_fee_cfg
        self._ev_calc = EVCalculator(pm_fee_cfg)

        self._screener = MarketScreener(cfg["screening"])
        self._fv_model = FairValueModel(cfg.get("fair_value", {}))
        self._mm = MarketMakerStrategy(cfg["market_making"], fee_cfg=pm_fee_cfg)
        self._risk = RiskManager(cfg["risk"])

        self._ofi: dict[str, OFITracker] = {}
        self._vpin: dict[str, VPINTracker] = {}

        self._positions: dict[str, int] = {}
        self._active_slugs: list[str] = []
        self._market_close_times: dict[str, datetime] = {}
        self._prev_realized_pnl: dict[str, float] = {}
        self._running = False

        self._client: PolymarketClient | None = None
        self._feed: PolymarketFeed | None = None
        self._orders: PolymarketOrderManager | None = None

    # ── Feed callbacks ────────────────────────────────────────────────────────

    async def _on_orderbook(self, ob: Orderbook):
        if not self._risk.enabled:
            return

        slug = ob.ticker
        ofi = self._ofi.setdefault(slug, OFITracker(**self._cfg.get("ofi", {})))
        vpin = self._vpin.get(slug)

        ofi_adj = ofi.update(ob)

        vpin_regime = FlowRegime.NORMAL
        vpin_mult = 1.0
        if vpin and vpin.has_data:
            vpin_regime = vpin.regime
            vpin_mult = vpin.spread_multiplier()
            if vpin_regime == FlowRegime.TOXIC:
                await self._orders.cancel_ticker(slug)
                logger.warning(f"VPIN TOXIC on {slug} — quotes pulled (VPIN={vpin.value:.2f})")
                return

        fv_result = self._fv_model.compute(ob, ofi_adjustment_cents=ofi_adj)
        if fv_result is None:
            return

        position = self._positions.get(slug, 0)
        time_remaining = self._time_remaining(slug)

        quote = self._mm.compute_quote(
            ticker=slug,
            fair_value=fv_result.fair_value,
            sigma_eff=fv_result.sigma_eff,
            position=position,
            confidence=fv_result.confidence,
            time_remaining=time_remaining,
            vpin_regime=vpin_regime,
            vpin_multiplier=vpin_mult,
        )

        if quote:
            bid_ok, bid_reason = self._risk.check_order(slug, quote.bid_size, self._positions)
            ask_ok, ask_reason = self._risk.check_order(slug, -quote.ask_size, self._positions)
            if not bid_ok:
                logger.debug(f"Risk suppressed bid on {slug}: {bid_reason}")
                quote.bid_size = 0
            if not ask_ok:
                logger.debug(f"Risk suppressed ask on {slug}: {ask_reason}")
                quote.ask_size = 0

            logger.debug(
                f"{slug}: fv={fv_result.fair_value:.1f}¢ "
                f"bid={quote.bid_price}¢ ask={quote.ask_price}¢ "
                f"vpin={vpin.value if vpin else 0:.2f}"
            )
            await self._orders.update(quote)

    async def _on_trade(self, event: TradeEvent):
        ob = self._feed.get_book(event.ticker)
        if ob is None:
            return
        mid = ob.mid_cents
        if mid is None:
            return
        vpin = self._vpin.setdefault(
            event.ticker, VPINTracker(**self._cfg.get("vpin", {}))
        )
        vpin.on_trade(event.price_cents, event.count, mid)

    def _time_remaining(self, slug: str) -> float:
        close_time = self._market_close_times.get(slug)
        if close_time is None:
            return 1.0
        if close_time.tzinfo is None:
            close_time = close_time.replace(tzinfo=timezone.utc)
        remaining_secs = (close_time - datetime.now(timezone.utc)).total_seconds()
        if remaining_secs <= 0:
            return self._mm._t_min
        return max(self._mm._t_min, min(1.0, remaining_secs / 86400.0))

    # ── Loops ─────────────────────────────────────────────────────────────────

    async def _market_refresh_loop(self):
        interval = self._cfg["screening"].get("market_refresh_interval_seconds", 300)
        while self._running:
            await asyncio.sleep(interval)
            if not self._running:
                break
            try:
                await self._refresh_markets()
            except Exception as exc:
                logger.error(f"Market refresh error: {exc}", exc_info=True)

    async def _position_sync_loop(self):
        interval = self._cfg["market_making"].get("position_sync_interval_seconds", 30)
        while self._running:
            await asyncio.sleep(interval)
            if not self._running:
                break
            try:
                await self._sync_positions()
            except Exception as exc:
                logger.error(f"Position sync error: {exc}", exc_info=True)
            if not self._risk.enabled:
                logger.warning(f"[bold red]HALTED[/bold red]: {self._risk.status.halt_reason}")
                await self._orders.cancel_all()

    async def _stale_order_loop(self):
        ttl = self._cfg["market_making"].get("stale_quote_ttl_seconds", 30)
        while self._running:
            await asyncio.sleep(ttl)
            if not self._running:
                break
            try:
                await self._orders.cancel_stale()
            except Exception as exc:
                logger.error(f"Stale order cleanup error: {exc}", exc_info=True)

    # ── Helpers ───────────────────────────────────────────────────────────────

    async def _refresh_markets(self):
        all_markets_pm = await self._client.get_all_open_markets()
        all_markets = [m.to_kalshi_market() for m in all_markets_pm]
        selected = self._screener.select(all_markets)
        new_slugs = [m.ticker for m in selected]

        # Store close times
        for pm_m in all_markets_pm:
            if pm_m.close_time and pm_m.slug in new_slugs:
                self._market_close_times[pm_m.slug] = pm_m.close_time

        old, new = set(self._active_slugs), set(new_slugs)
        for s in (old - new):
            await self._orders.cancel_ticker(s)
            self._ofi.pop(s, None)
            self._vpin.pop(s, None)
            self._market_close_times.pop(s, None)
        if old - new:
            await self._feed.unsubscribe(list(old - new))
        if new - old:
            await self._feed.subscribe(list(new - old))

        self._active_slugs = new_slugs
        self._print_market_table(selected)

    async def _sync_positions(self):
        positions = await self._client.get_positions()
        self._positions = {p.market_slug: int(p.net_position) for p in positions}
        self._risk.update_delta(self._positions)

        for p in positions:
            prev = self._prev_realized_pnl.get(p.market_slug, 0.0)
            delta = p.realized_pnl - prev
            if delta != 0.0:
                self._risk.record_pnl(delta)
            self._prev_realized_pnl[p.market_slug] = p.realized_pnl

        balance = await self._client.get_balance()
        risk = self._risk.summary()
        logger.info(
            f"Balance: ${balance.balance_dollars:.2f} USDC | "
            f"Markets: {len(self._active_slugs)} | "
            f"Daily P&L: ${risk['daily_pnl']:.2f} | "
            f"Delta: {risk['total_delta']}"
        )

    async def _reconcile_open_orders(self):
        """Cancel any resting orders from a previous bot instance."""
        try:
            open_orders = await self._client.get_orders()
            if open_orders:
                console.print(
                    f"[yellow]Reconciling {len(open_orders)} stale resting order(s) "
                    f"from previous run...[/yellow]"
                )
                for order in open_orders:
                    try:
                        await self._client.cancel_order(order.order_id)
                    except Exception as exc:
                        logger.warning(f"Failed to cancel stale order {order.order_id}: {exc}")
        except Exception as exc:
            logger.warning(f"Order reconciliation failed: {exc}")

    def _print_market_table(self, markets):
        table = Table(title=f"Active Markets — Polymarket US ({len(markets)})", show_lines=False)
        table.add_column("Slug", style="cyan", max_width=40)
        table.add_column("Bid", justify="right")
        table.add_column("Ask", justify="right")
        table.add_column("Mid", justify="right")
        table.add_column("Vol 24h", justify="right")
        table.add_column("Pos", justify="right")
        for m in markets:
            bid = f"{m.yes_bid}¢" if m.yes_bid else "-"
            ask = f"{m.yes_ask}¢" if m.yes_ask else "-"
            mid = f"{m.mid_price:.1f}¢" if m.mid_price else "-"
            pos = str(self._positions.get(m.ticker, 0))
            table.add_row(m.ticker, bid, ask, mid, str(m.volume_24h), pos)
        console.print(table)

    # ── Entry point ───────────────────────────────────────────────────────────

    async def run(self):
        pm_cfg = self._cfg["polymarket"]
        console.rule("[bold blue]Kannon Market Maker — Polymarket US[/bold blue]")

        key_id = os.environ["POLYMARKET_KEY_ID"]
        secret_key = os.environ["POLYMARKET_SECRET_KEY"]
        auth = PolymarketAuth(key_id, secret_key)

        async with PolymarketClient(
            base_url=pm_cfg["base_url"],
            auth=auth,
            rate_limit_rps=pm_cfg.get("rate_limit_rps", 1.0),
        ) as client:
            self._client = client
            self._orders = PolymarketOrderManager(
                client,
                stale_ttl_seconds=self._cfg["market_making"].get("stale_quote_ttl_seconds", 30),
            )
            ws_url = pm_cfg["ws_url"]
            self._feed = PolymarketFeed(ws_url=ws_url, auth=auth)
            self._feed.on_orderbook(self._on_orderbook)
            self._feed.on_trade(self._on_trade)
            self._running = True

            console.print(
                f"  Maker fees: [green]0%[/green]  |  "
                f"Tax rate: [cyan]{self._fee_cfg.marginal_tax_rate*100:.0f}%[/cyan]  |  "
                f"Gateway: [cyan]{pm_cfg['base_url']}[/cyan]\n"
            )

            await self._refresh_markets()
            await self._sync_positions()
            await self._reconcile_open_orders()

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

    bot = PolymarketBot(cfg)
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    def _handle_signal(sig, _frame):
        console.print(f"\n[yellow]Signal {sig.name} — shutting down...[/yellow]")
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
