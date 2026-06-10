"""Async REST client for the Kalshi Trade API v2."""
from __future__ import annotations
import asyncio
import logging
import time
import uuid
from typing import Any, Optional

import httpx

from .auth import KalshiAuth
from .models import (
    Balance, Market, MarketStatus, Orderbook, OrderbookLevel,
    Order, OrderAction, OrderStatus, OrderType, Position, Side,
)

logger = logging.getLogger(__name__)


class KalshiAPIError(Exception):
    def __init__(self, status_code: int, body: str):
        self.status_code = status_code
        self.body = body
        super().__init__(f"Kalshi API {status_code}: {body}")


def _parse_orderbook_fp(raw_levels: list) -> list[OrderbookLevel]:
    """Convert [[price_str, qty_str], ...] from the API into OrderbookLevel objects."""
    levels = []
    for entry in raw_levels:
        price_str, qty_str = entry[0], entry[1]
        price_cents = float(price_str) * 100.0
        levels.append(OrderbookLevel(price_cents=price_cents, quantity=float(qty_str)))
    return levels


class KalshiClient:
    def __init__(self, base_url: str, auth: KalshiAuth, rate_limit_rps: float = 10.0):
        self.base_url = base_url.rstrip("/")
        self.auth = auth
        self._rps = rate_limit_rps
        self._min_interval = 1.0 / rate_limit_rps
        self._last_request: float = 0.0
        self._http: Optional[httpx.AsyncClient] = None

    async def __aenter__(self) -> "KalshiClient":
        self._http = httpx.AsyncClient(timeout=30.0)
        return self

    async def __aexit__(self, *_):
        await self._http.aclose()

    async def _throttle(self):
        now = time.monotonic()
        wait = self._min_interval - (now - self._last_request)
        if wait > 0:
            await asyncio.sleep(wait)
        self._last_request = time.monotonic()

    async def _request(self, method: str, path: str, **kwargs) -> Any:
        await self._throttle()
        url = self.base_url + path
        headers = self.auth.sign_request(method, path)
        resp = await self._http.request(method, url, headers=headers, **kwargs)
        if not resp.is_success:
            raise KalshiAPIError(resp.status_code, resp.text)
        return resp.json() if resp.content else {}

    # ── Market data ──────────────────────────────────────────────────────────

    async def get_markets(
        self,
        status: str = "open",
        limit: int = 200,
        cursor: Optional[str] = None,
    ) -> tuple[list[Market], Optional[str]]:
        params: dict[str, Any] = {"limit": limit, "status": status}
        if cursor:
            params["cursor"] = cursor
        data = await self._request("GET", "/markets", params=params)
        markets = [Market(**m) for m in data.get("markets", [])]
        return markets, data.get("cursor")

    async def get_all_open_markets(self) -> list[Market]:
        markets: list[Market] = []
        cursor: Optional[str] = None
        while True:
            batch, cursor = await self.get_markets(cursor=cursor)
            markets.extend(batch)
            if not cursor:
                break
        logger.info(f"Fetched {len(markets)} open markets")
        return markets

    async def get_market(self, ticker: str) -> Market:
        data = await self._request("GET", f"/markets/{ticker}")
        return Market(**data["market"])

    async def get_orderbook(self, ticker: str, depth: int = 10) -> Orderbook:
        data = await self._request(
            "GET", f"/markets/{ticker}/orderbook", params={"depth": depth}
        )
        ob_raw = data.get("orderbook", {})
        yes_bids = _parse_orderbook_fp(ob_raw.get("yes_dollars_fp", ob_raw.get("yes", [])))
        no_bids = _parse_orderbook_fp(ob_raw.get("no_dollars_fp", ob_raw.get("no", [])))
        # Ensure sorted best-first
        yes_bids.sort(key=lambda x: x.price_cents, reverse=True)
        no_bids.sort(key=lambda x: x.price_cents, reverse=True)
        return Orderbook(ticker=ticker, yes_bids=yes_bids, no_bids=no_bids)

    # ── Orders ───────────────────────────────────────────────────────────────

    async def create_order(
        self,
        ticker: str,
        action: OrderAction,
        side: Side,
        order_type: OrderType,
        count: int,
        yes_price: int,
        client_order_id: Optional[str] = None,
    ) -> Order:
        payload: dict[str, Any] = {
            "ticker": ticker,
            "action": action.value,
            "side": side.value,
            "type": order_type.value,
            "count": count,
            "yes_price": yes_price,
            "client_order_id": client_order_id or str(uuid.uuid4()),
        }
        data = await self._request("POST", "/portfolio/orders", json=payload)
        return Order(**data["order"])

    async def cancel_order(self, order_id: str) -> Order:
        data = await self._request("DELETE", f"/portfolio/orders/{order_id}")
        return Order(**data["order"])

    async def get_orders(
        self,
        ticker: Optional[str] = None,
        status: Optional[str] = None,
    ) -> list[Order]:
        params: dict[str, Any] = {}
        if ticker:
            params["ticker"] = ticker
        if status:
            params["status"] = status
        data = await self._request("GET", "/portfolio/orders", params=params)
        return [Order(**o) for o in data.get("orders", [])]

    # ── Portfolio ─────────────────────────────────────────────────────────────

    async def get_positions(self) -> list[Position]:
        data = await self._request("GET", "/portfolio/positions")
        return [Position(**p) for p in data.get("market_positions", [])]

    async def get_balance(self) -> Balance:
        data = await self._request("GET", "/portfolio/balance")
        return Balance(**data)
