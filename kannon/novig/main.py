"""
Novig EV maker-bot entry point.

Lifecycle:
  1. Fetch fair values from sharp books (Pinnacle, Circa) via The Odds API.
  2. Fetch events available on Novig.
  3. Match events between the two sources by team-name similarity.
  4. For each matched event, compute EV for each outcome at current Novig odds.
  5. Place make bets where EV >= min_ev_threshold (default 5%).
  6. Background task monitors every pending order:
       - Cancels if EV drops below threshold (sharp lines moved).
       - Cancels if undercut (someone else is offering better odds).

Run:
    kannon-novig

Required env vars (.env):
    NOVIG_API_KEY    — Novig API key
    ODDS_API_KEY     — The Odds API key (free tier at the-odds-api.com)
"""
from __future__ import annotations
import asyncio
import logging
import os
import signal
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

import yaml
from dotenv import load_dotenv
from rich.console import Console
from rich.logging import RichHandler
from rich.table import Table

from .client import NovigClient, NovigAPIError
from .devig import calc_ev, min_odds_for_ev, better_odds
from .models import EVOpportunity, NovigOrder
from .order_monitor import OrderMonitor, _normalise
from .sharp_lines import OddsAPIClient

console = Console()
logger = logging.getLogger(__name__)


# ── Startup helpers ───────────────────────────────────────────────────────────

def setup_logging(level: str, log_file: str | None) -> None:
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


# ── Event matching ────────────────────────────────────────────────────────────

def _teams_match(a: str, b: str) -> bool:
    an, bn = _normalise(a), _normalise(b)
    return an == bn or an in bn or bn in an


def _events_match(
    novig_home: str, novig_away: str,
    odds_home: str, odds_away: str,
) -> bool:
    """True if the two team-pair descriptions are probably the same matchup."""
    return (
        (_teams_match(novig_home, odds_home) and _teams_match(novig_away, odds_away))
        or (_teams_match(novig_home, odds_away) and _teams_match(novig_away, odds_home))
    )


def _outcome_novig_key(outcome: str, novig_home: str, novig_away: str) -> str:
    """
    Map an Odds-API outcome name (e.g. "Kansas City Chiefs") to the
    corresponding Novig outcome name (often the same; may be abbreviated).

    If we can't map it, return it as-is and let fuzzy matching handle it.
    """
    if _teams_match(outcome, novig_home):
        return novig_home
    if _teams_match(outcome, novig_away):
        return novig_away
    return outcome


# ── Main bot ──────────────────────────────────────────────────────────────────

class NovigBot:
    """
    Scans for EV+ make-bet opportunities on Novig and manages the order lifecycle.
    """

    def __init__(self, cfg: dict):
        self._cfg = cfg
        novig_cfg = cfg.get("novig", {})
        odds_cfg = cfg.get("odds_api", {})

        novig_key = os.environ.get("NOVIG_API_KEY", "")
        odds_key = os.environ.get("ODDS_API_KEY", "")

        if not novig_key:
            console.print("[bold red]NOVIG_API_KEY not set — add it to .env[/bold red]")
            sys.exit(1)
        if not odds_key:
            console.print("[bold red]ODDS_API_KEY not set — add it to .env[/bold red]")
            sys.exit(1)

        self._novig = NovigClient(
            api_key=novig_key,
            rate_limit_rps=novig_cfg.get("rate_limit_rps", 2.0),
            base_url=novig_cfg.get("base_url"),
        )
        self._odds_client = OddsAPIClient(
            api_key=odds_key,
            bookmakers=odds_cfg.get("bookmakers", ["pinnacle", "circasports"]),
            cache_ttl_seconds=odds_cfg.get("cache_ttl_seconds", 60),
        )

        self._sports: list[str] = novig_cfg.get(
            "sports", ["americanfootball_nfl", "basketball_nba"]
        )
        self._min_ev: float = novig_cfg.get("min_ev_threshold", 0.05)
        self._default_stake: float = novig_cfg.get("default_stake_usd", 10.0)
        self._max_stake: float = novig_cfg.get("max_stake_usd", 50.0)
        self._devig_method: str = novig_cfg.get("devig_method", "power")
        self._scan_interval: float = novig_cfg.get("scan_interval_seconds", 60.0)
        self._max_per_event: int = novig_cfg.get("max_orders_per_event", 1)
        self._cancel_if_undercut: bool = novig_cfg.get("cancel_if_not_top_of_book", True)
        self._fee_rate: float = novig_cfg.get("fee_rate", 0.0)
        self._running = False

        # event_id -> list[order_id]
        self._active_orders: dict[str, list[str]] = {}
        self._monitor: Optional[OrderMonitor] = None

    async def run(self) -> None:
        async with self._novig, self._odds_client:
            self._monitor = OrderMonitor(
                novig=self._novig,
                odds_client=self._odds_client,
                sports=self._sports,
                min_ev_threshold=self._min_ev,
                monitor_interval_seconds=self._cfg.get("novig", {}).get(
                    "monitor_interval_seconds", 30.0
                ),
                cancel_if_not_top=self._cancel_if_undercut,
                ev_method=self._devig_method,
                novig_fee_rate=self._fee_rate,
            )
            self._running = True
            monitor_task = asyncio.create_task(self._monitor.run(), name="order-monitor")
            try:
                await self._main_loop()
            except asyncio.CancelledError:
                pass
            finally:
                self._monitor.stop()
                monitor_task.cancel()
                try:
                    await monitor_task
                except asyncio.CancelledError:
                    pass

    async def _main_loop(self) -> None:
        console.print(
            f"[bold green]NovigBot started[/bold green] — "
            f"sports={self._sports}, min_ev={self._min_ev:.0%}, "
            f"stake=${self._default_stake:.0f}–${self._max_stake:.0f}, "
            f"scan every {self._scan_interval:.0f}s"
        )
        while self._running:
            try:
                await self._scan_and_place()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("Scan error: %s", exc, exc_info=True)
            await asyncio.sleep(self._scan_interval)

    async def _scan_and_place(self) -> None:
        """One full scan cycle: find opportunities and place make bets."""

        # ── 1. Sharp-book fair values ─────────────────────────────────────────
        fair_values = await self._odds_client.get_fair_values(
            self._sports, method=self._devig_method
        )
        if not fair_values:
            logger.debug("No sharp lines available — skipping scan")
            return

        # ── 2. Novig events ───────────────────────────────────────────────────
        novig_events = []
        for sport in self._sports:
            try:
                novig_events.extend(await self._novig.get_events(sport=sport))
            except NovigAPIError as exc:
                logger.error("Novig events fetch failed for %s: %s", sport, exc)

        if not novig_events:
            logger.debug("No Novig events available")
            return

        # ── 3. Match events ───────────────────────────────────────────────────
        opportunities: list[EVOpportunity] = []

        for nev in novig_events:
            # Skip if we already have the max number of orders on this event
            existing = self._active_orders.get(nev.event_id, [])
            if len(existing) >= self._max_per_event:
                continue

            # Find matching fair value
            fv = next(
                (f for f in fair_values
                 if _events_match(nev.home_team, nev.away_team, f.home_team, f.away_team)),
                None,
            )
            if fv is None:
                continue

            # Fetch current order book to know available odds
            try:
                ob = await self._novig.get_orderbook(nev.event_id)
            except Exception as exc:
                logger.debug("Cannot fetch Novig orderbook for %s: %s", nev.event_id, exc)
                ob = {}

            # ── 4. Find EV+ lines per outcome ─────────────────────────────────
            for api_outcome, true_prob in fv.outcomes.items():
                novig_outcome = _outcome_novig_key(api_outcome, nev.home_team, nev.away_team)

                # Determine the odds we want to post
                outcome_book = ob.get(novig_outcome)
                if outcome_book and outcome_book.best_odds is not None:
                    # Try to be top of book: post slightly better than current best
                    target_odds = better_odds(outcome_book.best_odds, step=5)
                else:
                    # No book: post at the minimum odds that still clears our EV hurdle
                    try:
                        target_odds = min_odds_for_ev(true_prob, self._min_ev, self._fee_rate)
                    except Exception:
                        continue

                ev = calc_ev(true_prob, target_odds, self._fee_rate)
                if ev < self._min_ev:
                    continue

                opportunities.append(EVOpportunity(
                    odds_api_event_id=fv.event_id_odds_api,
                    novig_event_id=nev.event_id,
                    outcome=novig_outcome,
                    true_prob=true_prob,
                    novig_odds=target_odds,
                    ev_pct=ev,
                    stake_usd=min(self._default_stake, self._max_stake),
                ))

        if not opportunities:
            logger.debug("No EV+ opportunities found this scan")
            return

        # ── 5. Rank and place ─────────────────────────────────────────────────
        opportunities.sort(key=lambda o: o.ev_pct, reverse=True)
        self._print_opportunities(opportunities)

        for opp in opportunities:
            existing = self._active_orders.get(opp.novig_event_id, [])
            if len(existing) >= self._max_per_event:
                continue

            try:
                order = await self._novig.place_order(
                    event_id=opp.novig_event_id,
                    outcome=opp.outcome,
                    american_odds=opp.novig_odds,
                    stake_usd=opp.stake_usd,
                )
                order.true_prob_at_placement = opp.true_prob
                order.ev_at_placement = opp.ev_pct
                order.odds_api_event_id = opp.odds_api_event_id

                self._monitor.track(order, opp.odds_api_event_id)
                self._active_orders.setdefault(opp.novig_event_id, []).append(order.order_id)

                console.print(
                    f"[bold green]PLACED[/bold green] make bet | "
                    f"[cyan]{opp.outcome}[/cyan] {opp.novig_odds:+d} | "
                    f"true_prob={opp.true_prob:.1%}  EV=[green]{opp.ev_pct:.1%}[/green]  "
                    f"stake=${opp.stake_usd:.0f}  id={order.order_id}"
                )
            except NovigAPIError as exc:
                logger.error("Order placement failed for %s: %s", opp.outcome, exc)

    def _print_opportunities(self, opps: list[EVOpportunity]) -> None:
        table = Table(title="EV+ Opportunities", show_header=True, header_style="bold magenta")
        table.add_column("Outcome")
        table.add_column("True Prob", justify="right")
        table.add_column("Novig Odds", justify="right")
        table.add_column("EV", justify="right")
        table.add_column("Stake", justify="right")
        for opp in opps[:15]:
            table.add_row(
                opp.outcome,
                f"{opp.true_prob:.2%}",
                f"{opp.novig_odds:+d}",
                f"[green]{opp.ev_pct:.2%}[/green]",
                f"${opp.stake_usd:.0f}",
            )
        console.print(table)

    def shutdown(self) -> None:
        self._running = False
        if self._monitor:
            self._monitor.stop()


# ── CLI entry point ───────────────────────────────────────────────────────────

def main() -> None:
    load_dotenv()
    cfg = load_config()

    log_cfg = cfg.get("logging", {})
    setup_logging(log_cfg.get("level", "INFO"), log_cfg.get("file"))

    bot = NovigBot(cfg)
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    def _handle_signal(sig_name: str) -> None:
        console.print(f"\n[yellow]Received {sig_name} — shutting down …[/yellow]")
        bot.shutdown()
        for task in asyncio.all_tasks(loop):
            task.cancel()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _handle_signal, sig.name)

    try:
        loop.run_until_complete(bot.run())
    except (asyncio.CancelledError, KeyboardInterrupt):
        pass
    finally:
        loop.close()
        console.print("[bold]NovigBot stopped.[/bold]")


if __name__ == "__main__":
    main()
