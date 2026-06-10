"""WebSocket feed for real-time Polymarket US orderbook and trade data.

Markets channel:  wss://gateway.polymarket.us/v1/ws/markets
Private channel:  wss://gateway.polymarket.us/v1/ws/private

Market data messages deliver full orderbook snapshots (not deltas).
Trade messages carry the taker side so VPIN can be updated.
"""
from __future__ import annotations
import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Awaitable, Callable, Optional

import websockets
import websockets.exceptions

from .auth import PolymarketAuth
from .models import PMOrderIntent, parse_orderbook
from ..api.models import Orderbook
from ..api.feed import TradeEvent, OrderbookCallback, TradeCallback

logger = logging.getLogger(__name__)


class PolymarketFeed:
    """
    Maintains local orderbook state and fires callbacks for each update.
    Mirrors the MarketFeed interface so the rest of the bot is unchanged.
    """

    _MARKETS_PATH = "/v1/ws/markets"
    _PRIVATE_PATH = "/v1/ws/private"

    def __init__(self, ws_url: str, auth: PolymarketAuth):
        self.ws_url = ws_url.rstrip("/")
        self.auth = auth
        self._books: dict[str, Orderbook] = {}
        self._ob_callbacks: list[OrderbookCallback] = []
        self._trade_callbacks: list[TradeCallback] = []
        self._subscriptions: set[str] = set()
        self._ws = None
        self._sub_id = 0
        self._running = False

    # ── Public API ────────────────────────────────────────────────────────────

    def on_orderbook(self, cb: OrderbookCallback):
        self._ob_callbacks.append(cb)

    def on_trade(self, cb: TradeCallback):
        self._trade_callbacks.append(cb)

    def get_book(self, slug: str) -> Optional[Orderbook]:
        return self._books.get(slug)

    async def subscribe(self, slugs: list[str]):
        new = [s for s in slugs if s not in self._subscriptions]
        if not new:
            return
        self._subscriptions.update(new)
        if self._ws:
            await self._send_subscribe(new)

    async def unsubscribe(self, slugs: list[str]):
        for s in slugs:
            self._subscriptions.discard(s)
            self._books.pop(s, None)
        if self._ws and slugs:
            await self._send_unsubscribe(slugs)

    async def run(self):
        self._running = True
        url = self.ws_url + self._MARKETS_PATH
        while self._running:
            try:
                headers = self.auth.ws_headers(self._MARKETS_PATH)
                async with websockets.connect(
                    url,
                    additional_headers=headers,
                    ping_interval=20,
                    ping_timeout=10,
                ) as ws:
                    self._ws = ws
                    logger.info("Polymarket WebSocket connected")
                    if self._subscriptions:
                        await self._send_subscribe(list(self._subscriptions))
                    async for raw in ws:
                        await self._handle(json.loads(raw))
            except (websockets.exceptions.ConnectionClosed, OSError) as exc:
                logger.warning(f"Polymarket WebSocket disconnected ({exc}), reconnecting in 5s")
                self._ws = None
                await asyncio.sleep(5)
            except Exception as exc:
                logger.error(f"Polymarket WebSocket error: {exc}", exc_info=True)
                self._ws = None
                await asyncio.sleep(5)

    def stop(self):
        self._running = False

    # ── Wire protocol ─────────────────────────────────────────────────────────

    def _next_id(self) -> str:
        self._sub_id += 1
        return f"kannon-{self._sub_id}"

    async def _send_subscribe(self, slugs: list[str]):
        for channel in ("SUBSCRIPTION_TYPE_MARKET_DATA", "SUBSCRIPTION_TYPE_TRADE"):
            msg = {
                "requestId": self._next_id(),
                "subscriptionType": channel,
                "marketSlugs": slugs,
            }
            await self._ws.send(json.dumps(msg))

    async def _send_unsubscribe(self, slugs: list[str]):
        for channel in ("SUBSCRIPTION_TYPE_MARKET_DATA", "SUBSCRIPTION_TYPE_TRADE"):
            msg = {
                "requestId": self._next_id(),
                "action": "unsubscribe",
                "subscriptionType": channel,
                "marketSlugs": slugs,
            }
            await self._ws.send(json.dumps(msg))

    # ── Message handling ──────────────────────────────────────────────────────

    async def _handle(self, msg: dict):
        sub_type = msg.get("subscriptionType")

        if sub_type == "SUBSCRIPTION_TYPE_MARKET_DATA":
            market_data = msg.get("marketData", {})
            ob = self._parse_market_data(market_data)
            if ob:
                await self._fire_ob(ob)

        elif sub_type == "SUBSCRIPTION_TYPE_TRADE":
            event = self._parse_trade(msg.get("trade", {}))
            if event:
                await self._fire_trade(event)

    def _parse_market_data(self, payload: dict) -> Optional[Orderbook]:
        slug = payload.get("marketSlug")
        if not slug:
            return None
        bids = payload.get("bids", [])
        offers = payload.get("offers", [])
        ob = parse_orderbook(slug, bids, offers)
        self._books[slug] = ob
        return ob

    def _parse_trade(self, payload: dict) -> Optional[TradeEvent]:
        slug = payload.get("marketSlug")
        if not slug:
            return None
        price_raw = payload.get("price", {})
        qty_raw = payload.get("quantity", 0)
        taker_intent_raw = payload.get("takerIntent", "")

        try:
            price_cents = float(price_raw.get("value", 0)) * 100.0
            count = float(qty_raw)
        except (ValueError, TypeError):
            return None

        # Map taker intent to taker_side convention used by VPINTracker
        if taker_intent_raw in (
            PMOrderIntent.BUY_LONG.value,
            PMOrderIntent.SELL_SHORT.value,
        ):
            taker_side = "yes"   # aggressor bought YES
        else:
            taker_side = "no"    # aggressor sold YES / bought NO

        return TradeEvent(
            ticker=slug,
            price_cents=price_cents,
            count=count,
            taker_side=taker_side,
        )

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
