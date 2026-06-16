"""
Sharp-book line fetcher using The Odds API (the-odds-api.com).

Fetches Pinnacle + Circa odds for configured sports, devigs them
via the power method, and returns blended fair-value probabilities.

API key: set ODDS_API_KEY in .env.
Free tier: 500 requests/month. Responses are cached (default 60 s).
"""
from __future__ import annotations
import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

import httpx

from .devig import devig_power, devig_multiplicative, blend_fair_values
from .models import EventFairValue

logger = logging.getLogger(__name__)

# Relative trust weights — Pinnacle is the sharpest market globally
BOOK_WEIGHTS: dict[str, float] = {
    "pinnacle": 1.00,
    "circasports": 0.85,
    "betcircausa": 0.85,   # Circa Sports sometimes appears under this key
    "draftkings": 0.55,
    "fanduel": 0.55,
}
DEFAULT_WEIGHT = 0.40

DEFAULT_BOOKS = ["pinnacle", "circasports"]


class OddsAPIError(Exception):
    pass


class OddsAPIClient:
    """
    Async client for The Odds API v4.

    Docs: https://the-odds-api.com/liveapi/guides/v4/
    """

    BASE_URL = "https://api.the-odds-api.com/v4"

    def __init__(
        self,
        api_key: str,
        bookmakers: list[str] | None = None,
        cache_ttl_seconds: int = 60,
    ):
        self._api_key = api_key
        self._bookmakers = bookmakers or DEFAULT_BOOKS
        self._cache_ttl = cache_ttl_seconds
        # { cache_key: (data, fetched_at) }
        self._cache: dict[str, tuple[list, datetime]] = {}
        self._http: Optional[httpx.AsyncClient] = None
        self._lock = asyncio.Lock()

    async def __aenter__(self) -> "OddsAPIClient":
        self._http = httpx.AsyncClient(timeout=30.0)
        return self

    async def __aexit__(self, *_):
        await self._http.aclose()

    async def _get(self, path: str, params: dict) -> list | dict:
        params = {**params, "apiKey": self._api_key}
        resp = await self._http.get(f"{self.BASE_URL}{path}", params=params)
        remaining = resp.headers.get("x-requests-remaining", "?")
        logger.debug("Odds API GET %s — %s requests remaining", path, remaining)
        if resp.status_code == 401:
            raise OddsAPIError("Invalid Odds API key — set ODDS_API_KEY in .env")
        if resp.status_code == 422:
            raise OddsAPIError(f"Bad Odds API request: {resp.text}")
        resp.raise_for_status()
        return resp.json()

    async def get_sports(self) -> list[dict]:
        """Return all in-season sports available on the API."""
        return await self._get("/sports", {"all": "false"})

    async def get_odds(self, sport: str, markets: str = "h2h") -> list[dict]:
        """
        Fetch odds for a sport from configured sharp bookmakers.
        Results are cached for cache_ttl_seconds to limit API usage.
        """
        cache_key = f"{sport}_{markets}"
        now = datetime.now(timezone.utc)

        async with self._lock:
            cached = self._cache.get(cache_key)
            if cached:
                data, fetched_at = cached
                if (now - fetched_at).total_seconds() < self._cache_ttl:
                    return data

        data = await self._get(
            f"/sports/{sport}/odds",
            {
                "regions": "us",
                "markets": markets,
                "oddsFormat": "american",
                "bookmakers": ",".join(self._bookmakers),
            },
        )

        async with self._lock:
            self._cache[cache_key] = (data, now)

        return data

    def parse_event_fair_value(
        self, event: dict, method: str = "power"
    ) -> Optional[EventFairValue]:
        """
        Devig a single Odds API event response into blended fair probabilities.

        Blends all available sharp books weighted by sharpness (Pinnacle > Circa > …).
        Returns None if no bookmakers have h2h lines.
        """
        bookmakers = event.get("bookmakers", [])
        if not bookmakers:
            return None

        home = event["home_team"]
        away = event["away_team"]
        fair_values_per_book: list[dict[str, float]] = []
        weights: list[float] = []

        for bm in bookmakers:
            h2h = next((m for m in bm.get("markets", []) if m["key"] == "h2h"), None)
            if not h2h:
                continue
            outcomes = h2h.get("outcomes", [])
            if len(outcomes) < 2:
                continue

            odds_by_outcome = {o["name"]: float(o["price"]) for o in outcomes}
            try:
                fv = devig_power(odds_by_outcome) if method == "power" else devig_multiplicative(odds_by_outcome)
            except Exception as exc:
                logger.debug("Devig failed for %s: %s", bm["key"], exc)
                continue

            fair_values_per_book.append(fv)
            weights.append(BOOK_WEIGHTS.get(bm["key"], DEFAULT_WEIGHT))

        if not fair_values_per_book:
            return None

        blended = blend_fair_values(fair_values_per_book, weights)
        if not blended:
            return None

        try:
            commence_time = datetime.fromisoformat(
                event["commence_time"].replace("Z", "+00:00")
            )
        except Exception:
            return None

        return EventFairValue(
            event_id_odds_api=event["id"],
            home_team=home,
            away_team=away,
            sport=event.get("sport_key", ""),
            commence_time=commence_time,
            outcomes=blended,
            source_books=[bm["key"] for bm in bookmakers if bm.get("markets")],
        )

    async def get_fair_values(
        self, sports: list[str], method: str = "power"
    ) -> list[EventFairValue]:
        """
        Fetch and devig lines for all configured sports.

        Returns a flat list of EventFairValue objects, one per matchup.
        """
        results: list[EventFairValue] = []
        for sport in sports:
            try:
                events = await self.get_odds(sport)
                for event in events:
                    fv = self.parse_event_fair_value(event, method)
                    if fv:
                        results.append(fv)
            except OddsAPIError as exc:
                logger.error("Odds API error for sport %s: %s", sport, exc)
            except Exception as exc:
                logger.error("Unexpected error fetching %s: %s", sport, exc, exc_info=True)
        logger.debug("Fetched fair values for %d events across %d sports", len(results), len(sports))
        return results
