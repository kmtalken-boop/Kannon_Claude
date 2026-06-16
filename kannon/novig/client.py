"""
Novig REST API client.

╔══════════════════════════════════════════════════════════════════════════════╗
║  TODO — VERIFY AGAINST NOVIG'S ACTUAL API DOCS BEFORE RUNNING              ║
║                                                                              ║
║  The endpoints, payload field names, and response shapes below are based on  ║
║  common REST exchange patterns and must be confirmed against the real API.   ║
║                                                                              ║
║  How to get Novig API access:                                                ║
║    1. Log in at https://novig.us                                             ║
║    2. Look for a "Developer" or "API" section in your account settings       ║
║    3. Join their Discord (novig.us/discord) and ask in #developers           ║
║    4. Check https://docs.novig.us (or similar) for the official spec         ║
║                                                                              ║
║  Fields most likely to need adjustment:                                      ║
║    • BASE_URL                   (line ~25)                                   ║
║    • Endpoint paths in each method  (marked with "# TODO: verify path")      ║
║    • Request payload field names    (marked with "# TODO: verify fields")    ║
║    • Response field names           (marked inline)                          ║
║    • Auth header format             (Bearer vs X-API-Key vs custom)          ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations
import asyncio
import logging
import time
from datetime import datetime
from typing import Any, Optional

import httpx

from .models import NovigEvent, NovigOffer, NovigOrderbook, NovigOrder, NovigOrderStatus
from .devig import american_to_implied

logger = logging.getLogger(__name__)


class NovigAPIError(Exception):
    def __init__(self, status_code: int, body: str):
        self.status_code = status_code
        self.body = body
        super().__init__(f"Novig API {status_code}: {body}")


class NovigClient:
    """Async REST client for the Novig P2P betting exchange."""

    # TODO: Replace with actual Novig API base URL
    DEFAULT_BASE_URL = "https://api.novig.us"

    def __init__(
        self,
        api_key: str,
        rate_limit_rps: float = 2.0,
        base_url: str | None = None,
    ):
        self._api_key = api_key
        self.base_url = (base_url or self.DEFAULT_BASE_URL).rstrip("/")
        self._rps = rate_limit_rps
        self._min_interval = 1.0 / rate_limit_rps
        self._last_request: float = 0.0
        self._throttle_lock = asyncio.Lock()
        self._http: Optional[httpx.AsyncClient] = None

    async def __aenter__(self) -> "NovigClient":
        self._http = httpx.AsyncClient(
            timeout=30.0,
            headers={
                # TODO: Verify auth header format with Novig
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
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
        for attempt in range(4):
            resp = await self._http.request(method, url, **kwargs)
            if resp.status_code == 429:
                wait = 2.0 ** attempt
                logger.warning("Novig rate-limited — retrying in %.0fs", wait)
                await asyncio.sleep(wait)
                continue
            if resp.status_code in (502, 503, 504):
                wait = 2.0 ** attempt
                logger.warning("Novig %d — retrying in %.0fs", resp.status_code, wait)
                await asyncio.sleep(wait)
                continue
            if not resp.is_success:
                raise NovigAPIError(resp.status_code, resp.text)
            return resp.json() if resp.content else {}
        raise NovigAPIError(503, f"Novig unavailable after retries on {path}")

    # ── Events ───────────────────────────────────────────────────────────────

    async def get_events(self, sport: str | None = None) -> list[NovigEvent]:
        """
        Fetch upcoming events available for betting.

        TODO: Verify /v1/events path and response schema.
        Expected response: {"events": [{"id", "home_team", "away_team",
                                        "sport", "commence_time", "status"}]}
        """
        params: dict[str, Any] = {"status": "upcoming"}
        if sport:
            params["sport"] = sport

        data = await self._request("GET", "/v1/events", params=params)  # TODO: verify path
        events: list[NovigEvent] = []
        for e in data.get("events", data if isinstance(data, list) else []):
            try:
                ct_raw = e.get("commence_time") or e.get("commenceTime") or e.get("start_time", "")
                events.append(NovigEvent(
                    event_id=str(e.get("id") or e["event_id"]),
                    home_team=e.get("home_team") or e.get("homeTeam", ""),
                    away_team=e.get("away_team") or e.get("awayTeam", ""),
                    sport=e.get("sport") or e.get("sport_key", ""),
                    commence_time=datetime.fromisoformat(str(ct_raw).replace("Z", "+00:00")),
                    status=e.get("status", "upcoming"),
                ))
            except Exception as exc:
                logger.debug("Skipping Novig event %s: %s", e.get("id", "?"), exc)
        return events

    # ── Order book ───────────────────────────────────────────────────────────

    async def get_orderbook(
        self, event_id: str, market_type: str = "h2h"
    ) -> dict[str, NovigOrderbook]:
        """
        Fetch all resting make-bet offers for an event, keyed by outcome name.

        TODO: Verify /v1/events/{id}/offers path and response schema.
        Expected response: {"offers": [{"id", "outcome", "american_odds", "stake_usd"}]}
        """
        data = await self._request(  # TODO: verify path
            "GET",
            f"/v1/events/{event_id}/offers",
            params={"market_type": market_type},
        )

        offers_by_outcome: dict[str, list[NovigOffer]] = {}
        raw_offers = data.get("offers", data if isinstance(data, list) else [])
        for offer in raw_offers:
            outcome = str(
                offer.get("outcome") or offer.get("team") or offer.get("selection", "")
            )
            raw_odds = offer.get("american_odds") or offer.get("americanOdds") or offer.get("odds", 0)
            obj = NovigOffer(
                offer_id=str(offer.get("id") or offer.get("offer_id", "")),
                outcome=outcome,
                american_odds=int(raw_odds),
                stake_usd=float(
                    offer.get("stake_usd") or offer.get("stakeUsd") or offer.get("stake", 0)
                ),
            )
            offers_by_outcome.setdefault(outcome, []).append(obj)

        result: dict[str, NovigOrderbook] = {}
        for outcome, offers in offers_by_outcome.items():
            # Sort: lowest implied probability (= best decimal odds) first
            offers.sort(key=lambda o: american_to_implied(o.american_odds))
            result[outcome] = NovigOrderbook(
                event_id=event_id, outcome=outcome, offers=offers
            )
        return result

    # ── Orders ───────────────────────────────────────────────────────────────

    async def place_order(
        self,
        event_id: str,
        outcome: str,
        american_odds: int,
        stake_usd: float,
        market_type: str = "h2h",
    ) -> NovigOrder:
        """
        Place a 'make' (limit) order on Novig.

        TODO: Verify /v1/orders path and payload fields.
        """
        payload = {   # TODO: verify field names
            "event_id": event_id,
            "outcome": outcome,
            "american_odds": american_odds,
            "stake_usd": round(stake_usd, 2),
            "market_type": market_type,
            "type": "make",
        }
        data = await self._request("POST", "/v1/orders", json=payload)  # TODO: verify path
        o = data.get("order", data)
        return NovigOrder(
            order_id=str(o.get("id") or o.get("order_id", "")),
            event_id=str(o.get("event_id", event_id)),
            outcome=str(o.get("outcome", outcome)),
            american_odds=int(o.get("american_odds", american_odds)),
            stake_usd=float(o.get("stake_usd", stake_usd)),
            status=NovigOrderStatus(o.get("status", "pending")),
            created_at=_parse_dt(o.get("created_at") or o.get("createdAt")),
        )

    async def get_pending_orders(self) -> list[NovigOrder]:
        """
        Fetch all resting (unfilled) orders placed by this account.

        TODO: Verify /v1/orders path and response schema.
        """
        data = await self._request(  # TODO: verify path
            "GET", "/v1/orders", params={"status": "pending"}
        )
        orders: list[NovigOrder] = []
        raw = data.get("orders", data if isinstance(data, list) else [])
        for o in raw:
            try:
                orders.append(NovigOrder(
                    order_id=str(o.get("id") or o.get("order_id", "")),
                    event_id=str(o.get("event_id") or o.get("eventId", "")),
                    outcome=str(o.get("outcome") or o.get("team", "")),
                    american_odds=int(
                        o.get("american_odds") or o.get("americanOdds") or o.get("odds", 0)
                    ),
                    stake_usd=float(o.get("stake_usd") or o.get("stake", 0)),
                    status=NovigOrderStatus(o.get("status", "pending")),
                    created_at=_parse_dt(o.get("created_at") or o.get("createdAt")),
                ))
            except Exception as exc:
                logger.debug("Skipping order %s: %s", o.get("id", "?"), exc)
        return orders

    async def cancel_order(self, order_id: str) -> bool:
        """
        Cancel a pending order.

        TODO: Verify DELETE /v1/orders/{id} path.
        Returns True on success or if the order is already gone.
        """
        try:
            await self._request("DELETE", f"/v1/orders/{order_id}")  # TODO: verify path
            return True
        except NovigAPIError as exc:
            if exc.status_code == 404:
                return True   # already filled/cancelled
            logger.error("Failed to cancel order %s: %s", order_id, exc)
            return False


def _parse_dt(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except Exception:
        return None
