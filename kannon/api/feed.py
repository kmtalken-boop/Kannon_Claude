"""WebSocket feed for real-time Kalshi orderbook and trade updates."""
from __future__ import annotations
import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Awaitable, Callable, Optional

import websockets
import websockets.exceptions

from .auth import KalshiAuth
from .models import Orderbook, OrderbookLevel

logger = logging.getLogger(__name__)

OrderbookCallback = Callable[[Orderbook], Awaitable[None] | None]


@dataclass
class TradeEvent:
    """A single matched trade on Kalshi."""
    ticker: str
    price_cents: float
    count: float        # contracts traded
    taker_side: str     # "yes" or "no" — which side the aggressor was on


TradeCallback = Callable[[TradeEvent], Awaitable[None] | None]


class MarketFeed:
    """
    Maintains local orderbook state and emits trade events for subscribed markets
    via the Kalshi WebSocket orderbook_delta and trade channels.
    """

    _WS_PATH = "/trade-api/ws/v2"

    def __init__(self, ws_url: str, auth: KalshiAuth):
        self.ws_url = ws_url
        self.auth = auth
        self._books: dict[str, Orderbook] = {}
        self._ob_callbacks: list[OrderbookCallback] = []
        self._trade_callbacks: list[TradeCallback] = []
        self._subscriptions: set[str] = set()
        self._ws = None
        self._msg_id = 0
        self._running = False

    # ── Public API ────────────────────────────────────────────────────────────

    def on_orderbook(self, cb: OrderbookCallback):
        self._ob_callbacks.append(cb)

    def on_trade(self, cb: TradeCallback):
        self._trade_callbacks.append(cb)

    def get_book(self, ticker: str) -> Optional[Orderbook]:
        return self._books.get(ticker)

    async def subscribe(self, tickers: list[str]):
        new = [t for t in tickers if t not in self._subscriptions]
        if not new:
            return
        self._subscriptions.update(new)
        if self._ws:
            await self._subscribe_ws(new)

    async def unsubscribe(self, tickers: list[str]):
        for t in tickers:
            self._subscriptions.discard(t)
            self._books.pop(t, None)
        if self._ws and tickers:
            await self._unsubscribe_ws(tickers)

    async def run(self):
        self._running = True
        while self._running:
            try:
                headers = self.auth.ws_headers(self._WS_PATH)
                async with websockets.connect(
                    self.ws_url,
                    additional_headers=headers,
                    ping_interval=20,
                    ping_timeout=10,
                ) as ws:
                    self._ws = ws
                    logger.info("WebSocket connected")
                    if self._subscriptions:
                        await self._subscribe_ws(list(self._subscriptions))
                    async for raw in ws:
                        await self._handle(json.loads(raw))
            except (websockets.exceptions.ConnectionClosed, OSError) as exc:
                logger.warning(f"WebSocket disconnected ({exc}), reconnecting in 5s")
                self._ws = None
                await asyncio.sleep(5)
            except Exception as exc:
                logger.error(f"WebSocket error: {exc}", exc_info=True)
                self._ws = None
                await asyncio.sleep(5)

    def stop(self):
        self._running = False

    # ── Wire protocol ─────────────────────────────────────────────────────────

    def _next_id(self) -> int:
        self._msg_id += 1
        return self._msg_id

    async def _subscribe_ws(self, tickers: list[str]):
        for channel in ("orderbook_delta", "trade"):
            msg = {
                "id": self._next_id(),
                "cmd": "subscribe",
                "params": {"channels": [channel], "market_tickers": tickers},
            }
            await self._ws.send(json.dumps(msg))

    async def _unsubscribe_ws(self, tickers: list[str]):
        for channel in ("orderbook_delta", "trade"):
            msg = {
                "id": self._next_id(),
                "cmd": "unsubscribe",
                "params": {"channels": [channel], "market_tickers": tickers},
            }
            await self._ws.send(json.dumps(msg))

    # ── Message handling ──────────────────────────────────────────────────────

    async def _handle(self, msg: dict):
        msg_type = msg.get("type")
        payload = msg.get("msg", {})

        if msg_type == "orderbook_snapshot":
            ob = self._apply_snapshot(payload)
            if ob:
                await self._fire_ob(ob)

        elif msg_type == "orderbook_delta":
            ob = self._apply_delta(payload)
            if ob:
                await self._fire_ob(ob)

        elif msg_type == "trade":
            event = self._parse_trade(payload)
            if event:
                await self._fire_trade(event)

    def _apply_snapshot(self, payload: dict) -> Optional[Orderbook]:
        ticker = payload.get("market_ticker")
        if not ticker:
            return None
        yes_bids = self._parse_fp(payload.get("yes_dollars_fp", []))
        no_bids = self._parse_fp(payload.get("no_dollars_fp", []))
        yes_bids.sort(key=lambda x: x.price_cents, reverse=True)
        no_bids.sort(key=lambda x: x.price_cents, reverse=True)
        ob = Orderbook(ticker=ticker, yes_bids=yes_bids, no_bids=no_bids)
        self._books[ticker] = ob
        return ob

    def _apply_delta(self, payload: dict) -> Optional[Orderbook]:
        ticker = payload.get("market_ticker")
        ob = self._books.get(ticker)
        if ob is None:
            return None
        price_cents = float(payload["price_dollars"]) * 100.0
        delta = float(payload["delta_fp"])
        side = payload["side"]
        levels = ob.yes_bids if side == "yes" else ob.no_bids
        self._update_level(levels, price_cents, delta)
        return ob

    def _parse_trade(self, payload: dict) -> Optional[TradeEvent]:
        ticker = payload.get("market_ticker")
        if not ticker:
            return None
        price_str = payload.get("yes_price") or payload.get("price")
        count_str = payload.get("count") or payload.get("count_fp", "1")
        taker_side = payload.get("taker_side", "yes")
        if price_str is None:
            return None
        # yes_price in the trade channel may be an integer (cents) or dollar string
        try:
            price_val = float(price_str)
            # Heuristic: if value > 1, it's already in cents; otherwise multiply by 100
            price_cents = price_val if price_val > 1 else price_val * 100.0
            count = float(count_str)
        except (ValueError, TypeError):
            return None
        return TradeEvent(ticker=ticker, price_cents=price_cents, count=count, taker_side=taker_side)

    @staticmethod
    def _parse_fp(raw: list) -> list[OrderbookLevel]:
        levels = []
        for entry in raw:
            price_cents = float(entry[0]) * 100.0
            quantity = float(entry[1])
            levels.append(OrderbookLevel(price_cents=price_cents, quantity=quantity))
        return levels

    @staticmethod
    def _update_level(levels: list[OrderbookLevel], price_cents: float, delta: float):
        for lv in levels:
            if abs(lv.price_cents - price_cents) < 0.01:
                lv.quantity += delta
                if lv.quantity <= 0:
                    levels.remove(lv)
                return
        if delta > 0:
            levels.append(OrderbookLevel(price_cents=price_cents, quantity=delta))
            levels.sort(key=lambda x: x.price_cents, reverse=True)

    async def _fire_ob(self, ob: Orderbook):
        for cb in self._ob_callbacks:
            try:
                result = cb(ob)
                if asyncio.iscoroutine(result):
                    await result
            except Exception as exc:
                logger.error(f"Orderbook callback error: {exc}", exc_info=True)

    async def _fire_trade(self, event: TradeEvent):
        for cb in self._trade_callbacks:
            try:
                result = cb(event)
                if asyncio.iscoroutine(result):
                    await result
            except Exception as exc:
                logger.error(f"Trade callback error: {exc}", exc_info=True)
