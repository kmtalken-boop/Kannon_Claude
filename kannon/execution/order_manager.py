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

_DEFAULT_PRICE_MOVE_THRESHOLD = 3    # cents
_DEFAULT_QUOTE_COOLDOWN_SECONDS = 10


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
    lock: asyncio.Lock = None

    def __post_init__(self):
        self.lock = asyncio.Lock()


class OrderManager:
    """
    Maintains one resting bid and one resting ask per market.
    Uses cancel-and-replace when the desired price changes by more than threshold.
    Per-ticker locks allow concurrent quoting across different markets.
    """

    def __init__(
        self,
        client: KalshiClient,
        stale_ttl_seconds: float = 3600.0,
        price_move_threshold: int = _DEFAULT_PRICE_MOVE_THRESHOLD,
        quote_cooldown_seconds: float = _DEFAULT_QUOTE_COOLDOWN_SECONDS,
    ):
        self._client = client
        self._stale_ttl = stale_ttl_seconds
        self._price_move_threshold = price_move_threshold
        self._quote_cooldown = quote_cooldown_seconds
        self._quotes: dict[str, _MarketQuotes] = {}
        self._quotes_lock = asyncio.Lock()  # protects _quotes dict only

    async def update(self, quote: Quote):
        mq = await self._get_or_create(quote.ticker)
        async with mq.lock:
            now = time.monotonic()
            elapsed = now - mq.last_quoted_at
            bid_moved = mq.bid is None or abs(mq.bid.price - quote.bid_price) >= self._price_move_threshold
            ask_moved = mq.ask is None or abs(mq.ask.price - quote.ask_price) >= self._price_move_threshold
            if elapsed < self._quote_cooldown and not bid_moved and not ask_moved:
                return
            mq.last_quoted_at = now
            await self._update_side(mq, quote, is_bid=True)
            await self._update_side(mq, quote, is_bid=False)

    async def cancel_ticker(self, ticker: str):
        async with self._quotes_lock:
            mq = self._quotes.pop(ticker, None)
        if not mq:
            return
        async with mq.lock:
            ids = [r.order_id for r in (mq.bid, mq.ask) if r]
        await asyncio.gather(*[self._cancel(oid) for oid in ids])

    async def cancel_all(self):
        async with self._quotes_lock:
            all_mqs = list(self._quotes.values())
            self._quotes.clear()
        order_ids = []
        for mq in all_mqs:
            for r in (mq.bid, mq.ask):
                if r:
                    order_ids.append(r.order_id)
        await asyncio.gather(*[self._cancel(oid) for oid in order_ids])

    async def cancel_stale(self):
        """Cancel orders that have been resting longer than stale_ttl."""
        now = time.monotonic()
        async with self._quotes_lock:
            mqs = list(self._quotes.values())
        for mq in mqs:
            async with mq.lock:
                for attr in ("bid", "ask"):
                    resting: Optional[_RestingOrder] = getattr(mq, attr)
                    if resting and (now - resting.placed_at) > self._stale_ttl:
                        if await self._cancel(resting.order_id):
                            setattr(mq, attr, None)

    # ── Internal ──────────────────────────────────────────────────────────────

    async def _get_or_create(self, ticker: str) -> _MarketQuotes:
        async with self._quotes_lock:
            if ticker not in self._quotes:
                self._quotes[ticker] = _MarketQuotes(ticker=ticker)
            return self._quotes[ticker]

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
            and abs(resting.price - new_price) < self._price_move_threshold
            and resting.size == new_size
        ):
            return

        # Cancel old order — only proceed if cancel actually succeeded
        if resting:
            cancelled = await self._cancel(resting.order_id)
            if not cancelled:
                return  # leave mq unchanged; avoid placing a duplicate order
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

    async def _cancel(self, order_id: str) -> bool:
        """Returns True if the order is gone (cancelled or already filled/not found)."""
        try:
            await self._client.cancel_order(order_id)
            logger.debug(f"Cancelled order {order_id}")
            return True
        except KalshiAPIError as exc:
            if exc.status_code == 404:   # already filled or cancelled — order is gone
                return True
            logger.warning(f"Cancel failed {order_id}: {exc}")
            return False
