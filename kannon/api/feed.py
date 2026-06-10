"""WebSocket feed for real-time Kalshi orderbook updates."""
from __future__ import annotations
import asyncio
import json
import logging
from typing import Awaitable, Callable

import websockets
import websockets.exceptions

from .auth import KalshiAuth
from .models import Orderbook, OrderbookLevel

logger = logging.getLogger(__name__)

OrderbookCallback = Callable[[Orderbook], Awaitable[None] | None]


class OrderbookFeed:
    """
    Maintains a local orderbook state for subscribed markets by listening
    to the Kalshi WebSocket orderbook_delta channel.
    """

    _WS_PATH = "/trade-api/ws/v2"

    def __init__(self, ws_url: str, auth: KalshiAuth):
        self.ws_url = ws_url
        self.auth = auth
        self._books: dict[str, Orderbook] = {}
        self._callbacks: list[OrderbookCallback] = []
        self._subscriptions: set[str] = set()
        self._ws = None
        self._msg_id = 0
        self._running = False

    # ── Public API ────────────────────────────────────────────────────────────

    def on_update(self, callback: OrderbookCallback):
        self._callbacks.append(callback)

    def get(self, ticker: str) -> Orderbook | None:
        return self._books.get(ticker)

    async def subscribe(self, tickers: list[str]):
        new = [t for t in tickers if t not in self._subscriptions]
        if not new:
            return
        self._subscriptions.update(new)
        if self._ws:
            await self._send_subscribe(new)

    async def unsubscribe(self, tickers: list[str]):
        for t in tickers:
            self._subscriptions.discard(t)
            self._books.pop(t, None)
        if self._ws and tickers:
            await self._send_unsubscribe(tickers)

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
                        await self._send_subscribe(list(self._subscriptions))
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

    # ── Internal ──────────────────────────────────────────────────────────────

    def _next_id(self) -> int:
        self._msg_id += 1
        return self._msg_id

    async def _send_subscribe(self, tickers: list[str]):
        msg = {
            "id": self._next_id(),
            "cmd": "subscribe",
            "params": {
                "channels": ["orderbook_delta"],
                "market_tickers": tickers,
            },
        }
        await self._ws.send(json.dumps(msg))

    async def _send_unsubscribe(self, tickers: list[str]):
        msg = {
            "id": self._next_id(),
            "cmd": "unsubscribe",
            "params": {
                "channels": ["orderbook_delta"],
                "market_tickers": tickers,
            },
        }
        await self._ws.send(json.dumps(msg))

    def _parse_fp_levels(self, raw: list) -> list[OrderbookLevel]:
        levels = []
        for entry in raw:
            price_cents = float(entry[0]) * 100.0
            quantity = float(entry[1])
            levels.append(OrderbookLevel(price_cents=price_cents, quantity=quantity))
        return levels

    async def _handle(self, msg: dict):
        msg_type = msg.get("type")
        payload = msg.get("msg", {})

        if msg_type == "orderbook_snapshot":
            ticker = payload.get("market_ticker")
            yes_bids = self._parse_fp_levels(payload.get("yes_dollars_fp", []))
            no_bids = self._parse_fp_levels(payload.get("no_dollars_fp", []))
            yes_bids.sort(key=lambda x: x.price_cents, reverse=True)
            no_bids.sort(key=lambda x: x.price_cents, reverse=True)
            ob = Orderbook(ticker=ticker, yes_bids=yes_bids, no_bids=no_bids)
            self._books[ticker] = ob
            await self._fire(ob)

        elif msg_type == "orderbook_delta":
            ticker = payload.get("market_ticker")
            price_cents = float(payload["price_dollars"]) * 100.0
            delta = float(payload["delta_fp"])
            side = payload["side"]   # "yes" or "no"

            ob = self._books.get(ticker)
            if ob is None:
                # Haven't received snapshot yet; skip
                return

            if side == "yes":
                self._apply_delta(ob.yes_bids, price_cents, delta, ascending=False)
            else:
                self._apply_delta(ob.no_bids, price_cents, delta, ascending=False)

            await self._fire(ob)

    @staticmethod
    def _apply_delta(levels: list[OrderbookLevel], price_cents: float, delta: float, ascending: bool):
        """In-place update of a sorted level list."""
        for level in levels:
            if abs(level.price_cents - price_cents) < 0.01:
                level.quantity += delta
                if level.quantity <= 0:
                    levels.remove(level)
                return
        if delta > 0:
            levels.append(OrderbookLevel(price_cents=price_cents, quantity=delta))
            levels.sort(key=lambda x: x.price_cents, reverse=not ascending)

    async def _fire(self, ob: Orderbook):
        for cb in self._callbacks:
            try:
                result = cb(ob)
                if asyncio.iscoroutine(result):
                    await result
            except Exception as exc:
                logger.error(f"Orderbook callback error: {exc}", exc_info=True)
