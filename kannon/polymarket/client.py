"""Async REST client for the Polymarket US API.

Base URL: https://gateway.polymarket.us
Rate limit: 60 req/min on public endpoints.
"""
from __future__ import annotations
import asyncio
import logging
import time
from typing import Any, Optional

import httpx

from .auth import PolymarketAuth
from .models import (
    PMBalance, PMMarket, PMMarketState, PMOrder, PMOrderIntent,
    PMOrderType, PMOrderStatus, PMTIF, PMPrice, PMPosition,
    parse_orderbook,
)
from ..api.models import Orderbook

logger = logging.getLogger(__name__)


class PolymarketAPIError(Exception):
    def __init__(self, status_code: int, body: str):
        self.status_code = status_code
        self.body = body
        super().__init__(f"Polymarket API {status_code}: {body}")


class PolymarketClient:
    def __init__(
        self,
        base_url: str,
        auth: PolymarketAuth,
        rate_limit_rps: float = 1.0,  # conservative: 60/min = 1/s
    ):
        self.base_url = base_url.rstrip("/")
        self.auth = auth
        self._min_interval = 1.0 / rate_limit_rps
        self._last_request: float = 0.0
        self._http: Optional[httpx.AsyncClient] = None

    async def __aenter__(self) -> "PolymarketClient":
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

    async def _request(
        self,
        method: str,
        path: str,
        authenticated: bool = False,
        **kwargs,
    ) -> Any:
        await self._throttle()
        url = self.base_url + path
        headers = self.auth.sign_request(method, path) if authenticated else {
            "Content-Type": "application/json"
        }
        for attempt in range(5):
            resp = await self._http.request(method, url, headers=headers, **kwargs)
            if resp.status_code == 429:
                wait = 2.0 ** attempt
                logger.warning(f"Rate limited on {path}, retrying in {wait:.0f}s")
                await asyncio.sleep(wait)
                continue
            if not resp.is_success:
                raise PolymarketAPIError(resp.status_code, resp.text)
            return resp.json() if resp.content else {}
        raise PolymarketAPIError(429, f"Rate limit exhausted after 5 retries on {path}")

    # ── Market data (public) ──────────────────────────────────────────────────

    async def get_markets(
        self,
        limit: int = 200,
        cursor: Optional[str] = None,
    ) -> tuple[list[PMMarket], Optional[str]]:
        params: dict[str, Any] = {"limit": limit, "state": "MARKET_STATE_OPEN"}
        if cursor:
            params["cursor"] = cursor
        data = await self._request("GET", "/v1/markets", params=params)
        markets = [_parse_market(m) for m in data.get("markets", [])]
        return markets, data.get("cursor")

    async def get_all_open_markets(self) -> list[PMMarket]:
        markets: list[PMMarket] = []
        cursor: Optional[str] = None
        while True:
            batch, cursor = await self.get_markets(cursor=cursor)
            markets.extend(batch)
            if not cursor:
                break
        logger.info(f"Fetched {len(markets)} open Polymarket markets")
        return markets

    async def get_orderbook(self, slug: str) -> Orderbook:
        data = await self._request("GET", f"/v1/markets/{slug}/book")
        bids = data.get("bids", [])
        offers = data.get("offers", [])
        return parse_orderbook(slug, bids, offers)

    async def get_bbo(self, slug: str) -> dict:
        """Best bid/offer — lightweight alternative to full book."""
        return await self._request("GET", f"/v1/markets/{slug}/bbo")

    # ── Orders (authenticated) ────────────────────────────────────────────────

    async def create_order(
        self,
        slug: str,
        intent: PMOrderIntent,
        price_prob: float,      # 0.0–1.0
        quantity: int,
        tif: PMTIF = PMTIF.GTC,
    ) -> PMOrder:
        payload = {
            "marketSlug": slug,
            "intent": intent.value,
            "type": PMOrderType.LIMIT.value,
            "price": {"value": f"{price_prob:.4f}", "currency": "USD"},
            "quantity": quantity,
            "tif": tif.value,
        }
        data = await self._request("POST", "/v1/orders", authenticated=True, json=payload)
        return _parse_order(data.get("order", data))

    async def cancel_order(self, order_id: str) -> None:
        try:
            await self._request("DELETE", f"/v1/orders/{order_id}", authenticated=True)
        except PolymarketAPIError as exc:
            if exc.status_code != 404:
                raise

    async def cancel_all_orders(self) -> None:
        try:
            await self._request("DELETE", "/v1/orders", authenticated=True)
        except PolymarketAPIError as exc:
            logger.warning(f"cancel_all failed: {exc}")

    async def get_orders(self, slug: Optional[str] = None) -> list[PMOrder]:
        params: dict[str, Any] = {"status": PMOrderStatus.OPEN.value}
        if slug:
            params["marketSlug"] = slug
        data = await self._request("GET", "/v1/orders", authenticated=True, params=params)
        return [_parse_order(o) for o in data.get("orders", [])]

    # ── Portfolio (authenticated) ─────────────────────────────────────────────

    async def get_positions(self) -> list[PMPosition]:
        data = await self._request("GET", "/v1/portfolio/positions", authenticated=True)
        return [
            PMPosition(
                market_slug=p["marketSlug"],
                net_position=float(p.get("netPosition", 0)),
                realized_pnl=float(p.get("realizedPnl", 0)),
            )
            for p in data.get("positions", [])
        ]

    async def get_balance(self) -> PMBalance:
        data = await self._request("GET", "/v1/account/balances", authenticated=True)
        return PMBalance(
            available=float(data.get("available", data.get("availableBalance", 0))),
            total=float(data.get("total", data.get("totalBalance", 0))),
        )


# ── Parsers ───────────────────────────────────────────────────────────────────

def _parse_market(raw: dict) -> PMMarket:
    stats = raw.get("stats", {})
    bbo = raw.get("bbo", {})

    best_bid = None
    best_ask = None
    if bbo.get("bid"):
        best_bid = PMPrice(value=str(bbo["bid"]["value"]))
    if bbo.get("ask"):
        best_ask = PMPrice(value=str(bbo["ask"]["value"]))

    return PMMarket(
        slug=raw["slug"],
        title=raw.get("title", raw["slug"]),
        state=PMMarketState(raw.get("state", "MARKET_STATE_OPEN")),
        close_time=raw.get("closeTime"),
        tick_size=float(raw.get("tickSize", 0.01)),
        volume_24h=float(stats.get("volume24h", 0)),
        open_interest=float(stats.get("openInterest", 0)),
        best_bid=best_bid,
        best_ask=best_ask,
    )


def _parse_order(raw: dict) -> PMOrder:
    return PMOrder(
        order_id=raw["orderId"],
        market_slug=raw["marketSlug"],
        intent=PMOrderIntent(raw["intent"]),
        order_type=PMOrderType(raw.get("type", "ORDER_TYPE_LIMIT")),
        price=PMPrice(value=str(raw["price"]["value"])),
        quantity=float(raw["quantity"]),
        filled_quantity=float(raw.get("filledQuantity", 0)),
        status=PMOrderStatus(raw.get("status", "ORDER_STATUS_OPEN")),
        created_time=raw.get("createdTime"),
    )
