"""Kannon — Kalshi market making bot entry point."""
from __future__ import annotations
import asyncio
import logging
import os
import signal
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import yaml
from dotenv import load_dotenv
from rich.console import Console
from rich.logging import RichHandler
from rich.table import Table

from .api.auth import KalshiAuth
from .api.client import KalshiClient
from .api.feed import MarketFeed, TradeEvent
from .api.models import Orderbook
from .execution.order_manager import OrderManager
from .risk.risk_manager import RiskManager
from .strategy.arb import ArbScanner
from .strategy.fair_value import FairValueModel
from .strategy.fees import FeeConfig, EVCalculator
from .strategy.market_maker import MarketMakerStrategy
from .strategy.ofi import OFITracker
from .strategy.pricer import EventPricer
from .strategy.screener import MarketScreener
from .strategy.vpin import VPINTracker, FlowRegime

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

        fee_cfg = FeeConfig(**cfg.get("fees", {}))
        self._fee_cfg = fee_cfg
        self._ev_calc = EVCalculator(fee_cfg)

        self._screener = MarketScreener(cfg["screening"])
        self._fv_model = FairValueModel(cfg.get("fair_value", {}))
        self._mm = MarketMakerStrategy(cfg["market_making"], fee_cfg=fee_cfg)
        self._risk = RiskManager(cfg["risk"])
        self._arb_scanner = ArbScanner(fee_cfg)
        self._event_pricer = EventPricer()

        # Per-ticker microstructure trackers
        self._ofi: dict[str, OFITracker] = {}
        self._vpin: dict[str, VPINTracker] = {}

        self._positions: dict[str, int] = {}
        self._active_tickers: list[str] = []
        self._market_close_times: dict[str, datetime] = {}
        # Equity-based daily P&L tracking (replaces broken realized_pnl delta approach)
        self._equity_date: date = date.min   # forces reset on first sync
        self._daily_start_equity: float = 0.0
        self._running = False

        self._client: KalshiClient | None = None
        self._feed: MarketFeed | None = None
        self._orders: OrderManager | None = None

    # ── Feed callbacks ────────────────────────────────────────────────────────

    async def _on_orderbook(self, ob: Orderbook):
        if not self._risk.enabled:
            return

        ticker = ob.ticker
        ofi = self._ofi.setdefault(ticker, OFITracker(**self._cfg.get("ofi", {})))
        vpin = self._vpin.get(ticker)

        # OFI: real-time fair value adjustment
        ofi_adj = ofi.update(ob)

        # VPIN state (may not have data yet — falls back to NORMAL)
        vpin_regime = FlowRegime.NORMAL
        vpin_mult = 1.0
        if vpin and vpin.has_data:
            vpin_regime = vpin.regime
            vpin_mult = vpin.spread_multiplier()
            if vpin_regime == FlowRegime.TOXIC:
                # Pull all orders immediately on toxic flow
                await self._orders.cancel_ticker(ticker)
                logger.warning(f"VPIN TOXIC on {ticker} — quotes pulled (VPIN={vpin.value:.2f})")
                return

        fv_result = self._fv_model.compute(ob, ofi_adjustment_cents=ofi_adj)
        if fv_result is None:
            return

        position = self._positions.get(ticker, 0)
        time_remaining = self._time_remaining(ticker)

        quote = self._mm.compute_quote(
            ticker=ticker,
            fair_value=fv_result.fair_value,
            sigma_eff=fv_result.sigma_eff,
            position=position,
            confidence=fv_result.confidence,
            time_remaining=time_remaining,
            vpin_regime=vpin_regime,
            vpin_multiplier=vpin_mult,
        )

        if quote:
            # Risk-gate each side: suppress if adding more contracts would breach limits
            bid_ok, bid_reason = self._risk.check_order(ticker, quote.bid_size, self._positions)
            ask_ok, ask_reason = self._risk.check_order(ticker, -quote.ask_size, self._positions)
            if not bid_ok:
                logger.debug(f"Risk suppressed bid on {ticker}: {bid_reason}")
                quote.bid_size = 0
            if not ask_ok:
                logger.debug(f"Risk suppressed ask on {ticker}: {ask_reason}")
                quote.ask_size = 0

            logger.debug(
                f"{ticker}: fv={fv_result.fair_value:.1f}¢ "
                f"bid={quote.bid_price}¢ ask={quote.ask_price}¢ "
                f"ev_bid={quote.ev_bid*100:.2f}¢ ev_ask={quote.ev_ask*100:.2f}¢ "
                f"vpin={vpin.value if vpin else 0:.2f}"
            )
            await self._orders.update(quote)

    async def _on_trade(self, event: TradeEvent):
        """Feed trade events into the VPIN tracker for this market."""
        ob = self._feed.get_book(event.ticker)
        if ob is None:
            return
        mid = ob.mid_cents
        if mid is None:
            return

        vpin = self._vpin.setdefault(
            event.ticker,
            VPINTracker(**self._cfg.get("vpin", {}))
        )
        vpin.on_trade(event.price_cents, event.count, mid)

    def _time_remaining(self, ticker: str) -> float:
        """Normalised time remaining [0,1] based on stored market close_time."""
        close_time = self._market_close_times.get(ticker)
        if close_time is None:
            return 1.0
        if close_time.tzinfo is None:
            close_time = close_time.replace(tzinfo=timezone.utc)
        remaining_secs = (close_time - datetime.now(timezone.utc)).total_seconds()
        if remaining_secs <= 0:
            return self._mm._t_min
        # Normalize on a 7-day window: 7d → 1.0, 24h → 0.14, 1h → 0.006.
        # This causes A-S to widen spreads meaningfully as expiry approaches,
        # protecting against pin-risk on near-expiry markets.
        t = min(1.0, remaining_secs / (7 * 86400.0))
        return max(self._mm._t_min, t)

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
        all_markets = await self._client.get_all_open_markets()
        selected = self._screener.select(all_markets)
        new_tickers = [m.ticker for m in selected]

        # Store close times for time_remaining computation
        for m in selected:
            if m.close_time:
                self._market_close_times[m.ticker] = m.close_time

        old, new = set(self._active_tickers), set(new_tickers)
        for t in (old - new):
            await self._orders.cancel_ticker(t)
            self._ofi.pop(t, None)
            self._vpin.pop(t, None)
            self._market_close_times.pop(t, None)
        if old - new:
            await self._feed.unsubscribe(list(old - new))
        if new - old:
            await self._feed.subscribe(list(new - old))

        self._active_tickers = new_tickers
        self._print_market_table(selected)

        # Cross-market arb scan
        arb_opps = self._arb_scanner.scan(all_markets)
        if arb_opps:
            console.print(f"[bold yellow]ARB opportunities: {len(arb_opps)}[/bold yellow]")
            for opp in arb_opps:
                console.print(f"  [cyan]{opp.description}[/cyan]")

    async def _sync_positions(self):
        positions = await self._client.get_positions()
        self._positions = {p.ticker: p.market_exposure for p in positions}
        self._risk.update_delta(self._positions)

        balance = await self._client.get_balance()

        # Mark-to-market equity = cash + estimated unrealized position value.
        # Uses FairValueModel's last computed FV per ticker (50¢ prior for unknown markets).
        # This captures settlement losses that the API's realized_pnl_dollars field omits —
        # Kalshi only populates that field for explicit sells, not contract expirations.
        pos_value = sum(
            pos * self._fv_model._last_fv.get(ticker, 50.0) / 100.0
            for ticker, pos in self._positions.items()
        )
        equity = balance.balance_dollars + pos_value

        today = date.today()
        if today != self._equity_date:
            self._equity_date = today
            self._daily_start_equity = equity   # baseline for the session

        daily_pnl = equity - self._daily_start_equity
        self._risk.set_daily_pnl(daily_pnl)

        risk = self._risk.summary()
        logger.info(
            f"Balance: ${balance.balance_dollars:.2f} | "
            f"Equity: ${equity:.2f} | "
            f"Daily P&L: ${daily_pnl:+.2f} | "
            f"Markets: {len(self._active_tickers)} | "
            f"Delta: {risk['total_delta']}"
        )

    async def _reconcile_open_orders(self):
        """Cancel any resting orders left over from a previous bot instance."""
        try:
            open_orders = await self._client.get_orders(status="resting")
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
        table = Table(title=f"Active Markets ({len(markets)})", show_lines=False)
        table.add_column("Ticker", style="cyan")
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
            self._feed = MarketFeed(ws_url=kcfg["ws_url"], auth=auth)
            self._feed.on_orderbook(self._on_orderbook)
            self._feed.on_trade(self._on_trade)
            self._running = True

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

    bot = KalshiBot(cfg)
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
