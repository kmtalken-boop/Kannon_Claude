"""
Pending-order monitor for the Novig EV bot.

Runs as a background async task. Every monitor_interval_seconds it:
  1. Fetches pending orders from Novig (source of truth).
  2. Refreshes sharp-book fair values for all events we have orders in.
  3. For each pending order:
     a. Recomputes EV from fresh sharp lines.
     b. Checks whether we are still top-of-book on Novig.
     c. Cancels the order if EV < min_ev_threshold or we have been undercut.
"""
from __future__ import annotations
import asyncio
import logging
from typing import Optional

from .client import NovigClient
from .devig import calc_ev
from .models import EventFairValue, NovigOrder
from .sharp_lines import OddsAPIClient

logger = logging.getLogger(__name__)


class OrderMonitor:
    """
    Monitors resting make-bet orders and cancels those that are:
    - No longer +EV (sharp lines have moved against us), or
    - Undercut (someone else is now offering better odds, so takers will
      bypass us entirely).
    """

    def __init__(
        self,
        novig: NovigClient,
        odds_client: OddsAPIClient,
        sports: list[str],
        min_ev_threshold: float = 0.05,
        monitor_interval_seconds: float = 30.0,
        cancel_if_not_top: bool = True,
        ev_method: str = "power",
        novig_fee_rate: float = 0.0,
    ):
        self._novig = novig
        self._odds_client = odds_client
        self._sports = sports
        self._min_ev = min_ev_threshold
        self._interval = monitor_interval_seconds
        self._cancel_if_not_top = cancel_if_not_top
        self._ev_method = ev_method
        self._fee_rate = novig_fee_rate
        self._running = False

        # order_id -> NovigOrder (with odds_api_event_id populated)
        self._tracked: dict[str, NovigOrder] = {}

    # ── Public API ────────────────────────────────────────────────────────────

    def track(self, order: NovigOrder, odds_api_event_id: str) -> None:
        """Register a newly placed order for EV and book-position monitoring."""
        order.odds_api_event_id = odds_api_event_id
        self._tracked[order.order_id] = order
        logger.info(
            "Tracking order %s: %s %+d (true_prob=%.1f%%, EV=%.1f%%)",
            order.order_id, order.outcome, order.american_odds,
            order.true_prob_at_placement * 100, order.ev_at_placement * 100,
        )

    def untrack(self, order_id: str) -> None:
        self._tracked.pop(order_id, None)

    @property
    def tracked_count(self) -> int:
        return len(self._tracked)

    def stop(self) -> None:
        self._running = False

    async def run(self) -> None:
        """Main monitoring loop — run as an asyncio task."""
        self._running = True
        logger.info(
            "Order monitor started (interval=%.0fs, min_ev=%.0f%%, cancel_if_undercut=%s)",
            self._interval, self._min_ev * 100, self._cancel_if_not_top,
        )
        while self._running:
            try:
                await self._cycle()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("Monitor cycle error: %s", exc, exc_info=True)
            await asyncio.sleep(self._interval)
        logger.info("Order monitor stopped")

    # ── Internal ──────────────────────────────────────────────────────────────

    async def _cycle(self) -> None:
        if not self._tracked:
            return

        # 1. Fetch live pending orders from Novig
        try:
            live_orders = await self._novig.get_pending_orders()
            live_ids = {o.order_id for o in live_orders}
        except Exception as exc:
            logger.error("Could not fetch pending orders: %s", exc)
            return

        # Remove orders that are no longer pending (filled or already cancelled)
        gone = [oid for oid in list(self._tracked) if oid not in live_ids]
        for oid in gone:
            order = self._tracked.pop(oid)
            logger.info(
                "Order %s (%s %+d) left the book (filled or cancelled)",
                oid, order.outcome, order.american_odds,
            )

        if not self._tracked:
            return

        # 2. Refresh sharp-book fair values
        try:
            fair_values = await self._odds_client.get_fair_values(
                self._sports, method=self._ev_method
            )
            fv_map: dict[str, EventFairValue] = {fv.event_id_odds_api: fv for fv in fair_values}
        except Exception as exc:
            logger.error("Could not refresh sharp lines: %s", exc)
            return

        # 3. Evaluate each tracked order
        to_cancel: list[tuple[str, str]] = []   # (order_id, reason)

        for order_id, order in list(self._tracked.items()):
            fv = fv_map.get(order.odds_api_event_id)
            if fv is None:
                logger.debug(
                    "No fresh sharp line for event %s — skipping EV check",
                    order.odds_api_event_id,
                )
                continue

            true_prob = _find_prob(order.outcome, fv.outcomes)
            if true_prob is None:
                logger.debug("Outcome '%s' not found in fair values", order.outcome)
                continue

            ev = calc_ev(true_prob, order.american_odds, self._fee_rate)

            if ev < self._min_ev:
                to_cancel.append((
                    order_id,
                    f"EV dropped to {ev:.1%} < {self._min_ev:.0%} "
                    f"(true_prob={true_prob:.1%}, odds={order.american_odds:+d})",
                ))
                continue

            if self._cancel_if_not_top:
                try:
                    ob = await self._novig.get_orderbook(order.event_id)
                    outcome_book = ob.get(order.outcome) or ob.get(
                        _fuzzy_key(order.outcome, ob)
                    )
                    if outcome_book and not outcome_book.is_our_order_top(order_id):
                        best = outcome_book.best_odds
                        to_cancel.append((
                            order_id,
                            f"Undercut — book best is {best:+d}, ours is {order.american_odds:+d}",
                        ))
                except Exception as exc:
                    logger.debug("Could not check book position for %s: %s", order_id, exc)

        # 4. Cancel flagged orders
        for order_id, reason in to_cancel:
            order = self._tracked.get(order_id)
            if order:
                logger.info(
                    "Cancelling order %s (%s %+d): %s",
                    order_id, order.outcome, order.american_odds, reason,
                )
            ok = await self._novig.cancel_order(order_id)
            if ok:
                self._tracked.pop(order_id, None)

        if to_cancel:
            logger.info(
                "Monitor cycle complete — cancelled %d / %d tracked orders",
                len(to_cancel), len(self._tracked) + len(to_cancel),
            )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _normalise(s: str) -> str:
    return s.lower().strip().replace(".", "").replace("-", " ")


def _find_prob(outcome: str, probs: dict[str, float]) -> Optional[float]:
    """Find the true probability for an outcome, with fuzzy name matching."""
    # Exact match first
    if outcome in probs:
        return probs[outcome]
    # Case-insensitive
    on = _normalise(outcome)
    for key, p in probs.items():
        kn = _normalise(key)
        if kn == on or on in kn or kn in on:
            return p
    return None


def _fuzzy_key(outcome: str, d: dict) -> Optional[str]:
    """Return the key in d that best matches outcome, or None."""
    on = _normalise(outcome)
    for k in d:
        kn = _normalise(k)
        if kn == on or on in kn or kn in on:
            return k
    return None
