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

PRICE_MOVE_THRESHOLD = 1   # cents — don't replace order if price moved less than this


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
            tickers = list(self._quotes.keys())
        for ticker in tickers:
            await self.cancel_ticker(ticker)

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
            logger.debug(
                f"{side_str} {quote.ticker} {new_price}¢ x{new_size} "
                f"(fv={quote.fair_value:.1f}¢ res={quote.reservation_price:.1f}¢)"
            )
        except KalshiAPIError as exc:
            logger.error(f"Order placement failed on {quote.ticker}: {exc}")

    async def _cancel(self, order_id: str):
        try:
            await self._client.cancel_order(order_id)
            logger.debug(f"Cancelled {order_id}")
        except KalshiAPIError as exc:
            if exc.status_code != 404:   # 404 = already filled/cancelled
                logger.warning(f"Cancel failed {order_id}: {exc}")
