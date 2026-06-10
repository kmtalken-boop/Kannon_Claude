"""Order lifecycle management: place, track, and replace resting quotes."""
from __future__ import annotations
import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Optional

from ..api.client import KalshiClient, KalshiAPIError
from ..api.models import OrderAction, OrderType, Side
from ..strategy.market_maker import Quote

logger = logging.getLogger(__name__)

PRICE_MOVE_THRESHOLD = 3   # cents — replace order only if quote shifts by ≥ this much
QUOTE_COOLDOWN_SECONDS = 10  # minimum seconds between re-quotes per market


@dataclass
class _RestingOrder:
    order_id: str
    price: int          # cents
    size: int
    placed_at: float    # monotonic time


@dataclass
class _MarketQuotes:
    ticker: str
    bid: Optional[_RestingOrder] = None
    ask: Optional[_RestingOrder] = None
    last_quoted_at: float = 0.0  # monotonic time of last quote update


class OrderManager:
    """
    Maintains one resting bid and one resting ask per market.
    Uses cancel-and-replace when the desired price changes by more than threshold.
    """

    def __init__(self, client: KalshiClient, stale_ttl_seconds: float = 30.0):
        self._client = client
        self._stale_ttl = stale_ttl_seconds
        self._quotes: dict[str, _MarketQuotes] = {}
        self._lock = asyncio.Lock()

    async def update(self, quote: Quote):
        async with self._lock:
            mq = self._quotes.setdefault(quote.ticker, _MarketQuotes(ticker=quote.ticker))
            now = time.monotonic()
            # Cooldown: skip re-quote if prices haven't moved and we quoted recently.
            # Always process if we have no resting orders (first quote or after a cancel).
            elapsed = now - mq.last_quoted_at
            bid_moved = mq.bid is None or abs(mq.bid.price - quote.bid_price) >= PRICE_MOVE_THRESHOLD
            ask_moved = mq.ask is None or abs(mq.ask.price - quote.ask_price) >= PRICE_MOVE_THRESHOLD
            if elapsed < QUOTE_COOLDOWN_SECONDS and not bid_moved and not ask_moved:
                return
            mq.last_quoted_at = now
            await self._update_side(mq, quote, is_bid=True)
            await self._update_side(mq, quote, is_bid=False)

    async def cancel_ticker(self, ticker: str):
        async with self._lock:
            mq = self._quotes.get(ticker)
            if not mq:
                return
            for resting in [mq.bid, mq.ask]:
                if resting:
                    await self._cancel(resting.order_id)
            self._quotes.pop(ticker, None)

    async def cancel_all(self):
        async with self._lock:
            for ticker in list(self._quotes.keys()):
                mq = self._quotes.pop(ticker, None)
                if mq:
                    for resting in [mq.bid, mq.ask]:
                        if resting:
                            await self._cancel(resting.order_id)

    async def cancel_stale(self):
        """Cancel orders that have been resting longer than stale_ttl."""
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
        new_price = quote.bid_price if is_bid else quote.ask_price
        new_size = quote.bid_size if is_bid else quote.ask_size

        # Size of 0 means this side has been suppressed (e.g. by risk limits) — cancel only
        if new_size == 0:
            if resting:
                await self._cancel(resting.order_id)
                if is_bid:
                    mq.bid = None
                else:
                    mq.ask = None
            return

        # No change needed
        if (
            resting is not None
            and abs(resting.price - new_price) < PRICE_MOVE_THRESHOLD
            and resting.size == new_size
        ):
            return

        # Cancel old order
        if resting:
            await self._cancel(resting.order_id)
            if is_bid:
                mq.bid = None
            else:
                mq.ask = None

        # Place new order
        try:
            if is_bid:
                order = await self._client.create_order(
                    ticker=quote.ticker,
                    action=OrderAction.BUY,
                    side=Side.YES,
                    order_type=OrderType.LIMIT,
                    count=new_size,
                    yes_price=new_price,
                )
                mq.bid = _RestingOrder(order.order_id, new_price, new_size, time.monotonic())
            else:
                # Ask = SELL YES
                order = await self._client.create_order(
                    ticker=quote.ticker,
                    action=OrderAction.SELL,
                    side=Side.YES,
                    order_type=OrderType.LIMIT,
                    count=new_size,
                    yes_price=new_price,
                )
                mq.ask = _RestingOrder(order.order_id, new_price, new_size, time.monotonic())

            side_str = "BID" if is_bid else "ASK"
            logger.info(
                f"QUOTE {side_str} {quote.ticker} {new_price}¢×{new_size} "
                f"(fv={quote.fair_value:.1f}¢ spread={quote.ask_price - quote.bid_price}¢)"
            )
        except KalshiAPIError as exc:
            logger.error(f"Order placement failed on {quote.ticker}: {exc}")

    async def _cancel(self, order_id: str):
        try:
            await self._client.cancel_order(order_id)
            logger.debug(f"Cancelled order {order_id}")
        except KalshiAPIError as exc:
            if exc.status_code != 404:   # 404 = already filled/cancelled
                logger.warning(f"Cancel failed {order_id}: {exc}")
