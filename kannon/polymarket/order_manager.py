"""Order lifecycle management for Polymarket US.

Maintains one resting bid (BUY_LONG) and one resting ask (SELL_LONG) per market.
Mirrors the Kalshi OrderManager interface so the strategy layer is unchanged.
"""
from __future__ import annotations
import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Optional

from .client import PolymarketClient, PolymarketAPIError
from .models import PMOrderIntent, PMTIF
from ..strategy.market_maker import Quote

logger = logging.getLogger(__name__)

PRICE_MOVE_THRESHOLD_CENTS = 1  # don't replace if price moved less than 1¢


@dataclass
class _RestingOrder:
    order_id: str
    price_cents: int
    size: int
    placed_at: float


@dataclass
class _MarketQuotes:
    slug: str
    bid: Optional[_RestingOrder] = None
    ask: Optional[_RestingOrder] = None


class PolymarketOrderManager:
    def __init__(self, client: PolymarketClient, stale_ttl_seconds: float = 30.0):
        self._client = client
        self._stale_ttl = stale_ttl_seconds
        self._quotes: dict[str, _MarketQuotes] = {}
        self._lock = asyncio.Lock()

    async def update(self, quote: Quote):
        async with self._lock:
            mq = self._quotes.setdefault(quote.ticker, _MarketQuotes(slug=quote.ticker))
            await self._update_side(mq, quote, is_bid=True)
            await self._update_side(mq, quote, is_bid=False)

    async def cancel_slug(self, slug: str):
        async with self._lock:
            mq = self._quotes.get(slug)
            if not mq:
                return
            for resting in [mq.bid, mq.ask]:
                if resting:
                    await self._cancel(resting.order_id)
            self._quotes.pop(slug, None)

    # Alias used by main.py (same interface as Kalshi OrderManager)
    async def cancel_ticker(self, ticker: str):
        await self.cancel_slug(ticker)

    async def cancel_all(self):
        async with self._lock:
            for slug in list(self._quotes.keys()):
                mq = self._quotes.pop(slug, None)
                if mq:
                    for resting in [mq.bid, mq.ask]:
                        if resting:
                            await self._cancel(resting.order_id)

    async def cancel_stale(self):
        now = time.monotonic()
        async with self._lock:
            for mq in self._quotes.values():
                for attr in ("bid", "ask"):
                    resting: Optional[_RestingOrder] = getattr(mq, attr)
                    if resting and (now - resting.placed_at) > self._stale_ttl:
                        await self._cancel(resting.order_id)
                        setattr(mq, attr, None)

    # ── Internal ──────────────────────────────────────────────────────────────

    async def _update_side(self, mq: _MarketQuotes, quote: Quote, is_bid: bool):
        resting: Optional[_RestingOrder] = mq.bid if is_bid else mq.ask
        new_price_cents = quote.bid_price if is_bid else quote.ask_price
        new_size = quote.bid_size if is_bid else quote.ask_size

        if new_size == 0:
            if resting:
                await self._cancel(resting.order_id)
                if is_bid:
                    mq.bid = None
                else:
                    mq.ask = None
            return

        if (
            resting is not None
            and abs(resting.price_cents - new_price_cents) < PRICE_MOVE_THRESHOLD_CENTS
            and resting.size == new_size
        ):
            return

        if resting:
            await self._cancel(resting.order_id)
            if is_bid:
                mq.bid = None
            else:
                mq.ask = None

        intent = PMOrderIntent.BUY_LONG if is_bid else PMOrderIntent.SELL_LONG
        try:
            order = await self._client.create_order(
                slug=quote.ticker,
                intent=intent,
                price_prob=new_price_cents / 100.0,
                quantity=new_size,
                tif=PMTIF.GTC,
            )
            resting_new = _RestingOrder(
                order_id=order.order_id,
                price_cents=new_price_cents,
                size=new_size,
                placed_at=time.monotonic(),
            )
            if is_bid:
                mq.bid = resting_new
            else:
                mq.ask = resting_new

            side_str = "BID" if is_bid else "ASK"
            logger.debug(
                f"{side_str} {quote.ticker} {new_price_cents}¢ x{new_size} "
                f"(fv={quote.fair_value:.1f}¢)"
            )
        except PolymarketAPIError as exc:
            logger.error(f"Order placement failed on {quote.ticker}: {exc}")

    async def _cancel(self, order_id: str):
        try:
            await self._client.cancel_order(order_id)
            logger.debug(f"Cancelled {order_id}")
        except PolymarketAPIError as exc:
            if exc.status_code != 404:
                logger.warning(f"Cancel failed {order_id}: {exc}")
