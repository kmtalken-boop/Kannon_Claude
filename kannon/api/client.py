"""Async REST client for the Kalshi Trade API v2."""
from __future__ import annotations
import asyncio
import logging
import time
import uuid
from typing import Any, Optional
from urllib.parse import urlparse

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
        self._base_path = urlparse(self.base_url).path  # e.g. "/trade-api/v2"
        self.auth = auth
        self._rps = rate_limit_rps
        self._min_interval = 1.0 / rate_limit_rps
        self._last_request: float = 0.0
        self._throttle_lock = asyncio.Lock()
        self._http: Optional[httpx.AsyncClient] = None

    async def __aenter__(self) -> "KalshiClient":
        self._http = httpx.AsyncClient(timeout=30.0)
        return self

    async def __aexit__(self, *_):
        await self._http.aclose()

    async def _throttle(self):
        async with self._throttle_lock:
            now = time.monotonic()
            wait = self._min_interval - (now - self._last_request)
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_request = time.monotonic()

    async def _request(self, method: str, path: str, **kwargs) -> Any:
        await self._throttle()
        url = self.base_url + path
        full_path = self._base_path + path
        for attempt in range(5):
            headers = self.auth.sign_request(method, full_path)
            resp = await self._http.request(method, url, headers=headers, **kwargs)
            if resp.status_code == 429:
                wait = 2.0 ** attempt
                logger.warning(f"Rate limited on {path}, retrying in {wait:.0f}s (attempt {attempt + 1}/5)")
                await asyncio.sleep(wait)
                continue
            if resp.status_code == 503:
                wait = 2.0 ** attempt
                logger.warning(f"Exchange unavailable on {path}, retrying in {wait:.0f}s (attempt {attempt + 1}/5)")
                await asyncio.sleep(wait)
                continue
            if not resp.is_success:
                raise KalshiAPIError(resp.status_code, resp.text)
            return resp.json() if resp.content else {}
        raise KalshiAPIError(503, f"Exchange unavailable after 5 retries on {path}")

    # ── Market data ──────────────────────────────────────────────────────────

    async def get_markets(
        self,
        status: str = "open",
        limit: int = 200,
        cursor: Optional[str] = None,
        min_close_ts: Optional[int] = None,
        max_close_ts: Optional[int] = None,
    ) -> tuple[list[Market], Optional[str]]:
        params: dict[str, Any] = {"limit": limit, "status": status}
        if cursor:
            params["cursor"] = cursor
        if min_close_ts is not None:
            params["min_close_ts"] = min_close_ts
        if max_close_ts is not None:
            params["max_close_ts"] = max_close_ts
        data = await self._request("GET", "/markets", params=params)
        markets = []
        for m in data.get("markets", []):
            try:
                markets.append(Market(**m))
            except Exception as exc:
                logger.debug(f"Skipping market {m.get('ticker', '?')}: {exc}")
        return markets, data.get("cursor")

    async def get_all_open_markets(
        self,
        max_pages: int = 60,
        excluded_prefixes: tuple[str, ...] = (),
        max_close_ts: Optional[int] = None,
    ) -> list[Market]:
        """Fetch open markets, paginating until the cursor is exhausted or
        max_pages × 200 candidates have been scanned.

        max_close_ts (if given) is sent server-side so far-future markets never
        count against the page budget. excluded_prefixes are dropped from each
        page as it's fetched — some series (e.g. multi-game extended sports
        props) can have thousands of entries and would otherwise crowd out
        every real market within the page budget.
        """
        markets: list[Market] = []
        cursor: Optional[str] = None
        for _ in range(max_pages):
            batch, cursor = await self.get_markets(cursor=cursor, max_close_ts=max_close_ts)
            for m in batch:
                if not any(m.ticker.startswith(p) for p in excluded_prefixes):
                    markets.append(m)
            if not cursor:
                break
        logger.info(f"Fetched {len(markets)} open markets (after prefix exclusion)")
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
        # V2 single-book YES-perspective: bid=buy YES, ask=sell YES.
        # NO side flips: buy NO = sell YES = ask; sell NO = buy YES = bid.
        if action == OrderAction.BUY:
            book_side = "bid" if side == Side.YES else "ask"
        else:
            book_side = "ask" if side == Side.YES else "bid"

        payload: dict[str, Any] = {
            "ticker": ticker,
            "client_order_id": client_order_id or str(uuid.uuid4()),
            "side": book_side,
            "count": f"{count:.2f}",
            "price": f"{yes_price / 100:.4f}",
            "time_in_force": "good_till_canceled",
            "self_trade_prevention_type": "taker_at_cross",
        }
        data = await self._request("POST", "/portfolio/events/orders", json=payload)
        # V2 returns a flat object (no "order" wrapper); Order model handles sparse fields
        return Order(**data)

    async def cancel_order(self, order_id: str) -> None:
        await self._request("DELETE", f"/portfolio/events/orders/{order_id}")

    async def get_orders(
        self,
        ticker: Optional[str] = None,
        status: Optional[str] = None,
    ) -> list[Order]:
        all_orders: list[Order] = []
        cursor: Optional[str] = None
        while True:
            params: dict[str, Any] = {"limit": 100}
            if ticker:
                params["ticker"] = ticker
            if status:
                params["status"] = status
            if cursor:
                params["cursor"] = cursor
            data = await self._request("GET", "/portfolio/orders", params=params)
            for o in data.get("orders", []):
                try:
                    all_orders.append(Order(**o))
                except Exception as exc:
                    logger.debug(f"Skipping order {o.get('order_id', '?')}: {exc}")
            cursor = data.get("cursor")
            if not cursor:
                break
        return all_orders

    # ── Portfolio ─────────────────────────────────────────────────────────────

    async def get_positions(self) -> list[Position]:
        all_positions: list[Position] = []
        cursor: Optional[str] = None
        while True:
            params: dict[str, Any] = {"limit": 100}
            if cursor:
                params["cursor"] = cursor
            data = await self._request("GET", "/portfolio/positions", params=params)
            for p in data.get("market_positions", []):
                try:
                    all_positions.append(Position(**p))
                except Exception as exc:
                    logger.debug(f"Skipping position {p.get('ticker', '?')}: {exc}")
            cursor = data.get("cursor")
            if not cursor:
                break
        return all_positions

    async def get_balance(self) -> Balance:
        data = await self._request("GET", "/portfolio/balance")
        return Balance(**data)
