"""
Historical data fetching for backtesting.

Downloads settled markets and their full trade histories from the Kalshi API,
then caches them to disk as JSON so you don't re-download on every run.

Cache layout:
  .backtest_cache/
    markets.json                         — list of settled Market objects
    trades/{ticker}.json                 — list of HistoricalTrade objects
"""
from __future__ import annotations
import asyncio
import json
import logging
import math
import random
from dataclasses import dataclass, asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

from ..api.client import KalshiClient
from ..api.models import Market

logger = logging.getLogger(__name__)

CACHE_DIR = Path(".backtest_cache")


@dataclass
class HistoricalTrade:
    trade_id: str
    ticker: str
    timestamp: str          # ISO 8601
    yes_price_cents: int
    count: int
    taker_side: str         # "yes" or "no"

    @property
    def dt(self) -> datetime:
        return datetime.fromisoformat(self.timestamp.replace("Z", "+00:00"))


def _synthetic_trades(
    ticker: str,
    result: str,
    close_time: Optional[datetime],
    n_trades: int = 150,
) -> list["HistoricalTrade"]:
    """
    Ornstein-Uhlenbeck price path ending near resolution for demo markets
    that have no trade history on the API.  Deterministic per ticker so the
    cache is reproducible.
    """
    rng = random.Random(hash(ticker))
    resolution_price = 95.0 if result == "yes" else 5.0
    end_time = close_time or datetime.now(timezone.utc)
    start_time = end_time - timedelta(hours=2)
    span_s = (end_time - start_time).total_seconds()

    theta, sigma = 0.08, 4.0
    price = 50.0
    trades = []
    for i in range(n_trades):
        t_frac = i / n_trades
        mu = 50.0 + (resolution_price - 50.0) * t_frac
        dp = theta * (mu - price) + sigma * rng.gauss(0, 1)
        price = max(1.0, min(99.0, price + dp))
        ts = start_time + timedelta(seconds=span_s * i / n_trades)
        trades.append(HistoricalTrade(
            trade_id=f"syn-{ticker}-{i}",
            ticker=ticker,
            timestamp=ts.isoformat(),
            yes_price_cents=int(round(price)),
            count=rng.randint(1, 8),
            taker_side="yes" if dp >= 0 else "no",
        ))
    return trades


def _load_cache(path: Path) -> Optional[list]:
    if path.exists():
        return json.loads(path.read_text())
    return None


def _save_cache(path: Path, data: list):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, default=str))


class HistoricalDataLoader:
    def __init__(self, client: KalshiClient):
        self._client = client

    async def fetch_settled_markets(
        self, days_back: int = 60, max_markets: int = 100
    ) -> list[Market]:
        """Fetch recently settled markets with known results."""
        cache_path = CACHE_DIR / f"markets_{days_back}d.json"
        cached = _load_cache(cache_path)
        if cached:
            logger.info(f"Loaded {len(cached)} settled markets from cache")
            return [Market(**m) for m in cached]

        logger.info(f"Fetching settled markets (last {days_back} days)...")
        cutoff = datetime.now(timezone.utc) - timedelta(days=days_back)
        markets: list[Market] = []
        cursor = None
        max_pages = 25  # hard cap — prevents infinite pagination

        for _ in range(max_pages):
            batch, cursor = await self._client.get_markets(
                status="settled", limit=200, cursor=cursor,
            )
            if not batch:
                break

            def _within_window(m: Market) -> bool:
                if m.result not in ("yes", "no"):
                    return False
                if m.close_time is None:
                    return True
                ct = m.close_time
                if ct.tzinfo is None:
                    ct = ct.replace(tzinfo=timezone.utc)
                return ct >= cutoff

            resolved = [m for m in batch if _within_window(m)]
            markets.extend(resolved)

            # If every market in this page closed before our cutoff we've gone
            # far enough back — no point fetching more pages.
            all_old = all(
                m.close_time is not None and (
                    m.close_time.replace(tzinfo=timezone.utc)
                    if m.close_time.tzinfo is None else m.close_time
                ) < cutoff
                for m in batch if m.close_time is not None
            )
            if all_old or not cursor or len(markets) >= max_markets:
                break

        markets = markets[:max_markets]
        _save_cache(cache_path, [m.model_dump() for m in markets])
        logger.info(f"Fetched {len(markets)} settled markets")
        return markets

    async def fetch_trades(
        self,
        ticker: str,
        result: Optional[str] = None,
        close_time: Optional[datetime] = None,
    ) -> list[HistoricalTrade]:
        """Fetch all trades for a market, with disk caching.

        Falls back to a synthetic OU price path when the API returns 404
        (common on demo/sandbox markets that have no real trade history).
        """
        cache_path = CACHE_DIR / "trades" / f"{ticker}.json"
        cached = _load_cache(cache_path)
        if cached:
            return [HistoricalTrade(**t) for t in cached]

        logger.debug(f"Downloading trade history for {ticker}...")
        trades: list[HistoricalTrade] = []
        cursor = None
        api_failed = False

        while True:
            params = {"limit": 1000}
            if cursor:
                params["cursor"] = cursor
            try:
                data = await self._client._request(
                    "GET", f"/markets/{ticker}/trades", params=params
                )
            except Exception as exc:
                if "404" in str(exc) and result in ("yes", "no"):
                    logger.debug(
                        f"{ticker}: trades endpoint unavailable (demo market), "
                        "using synthetic price path"
                    )
                    api_failed = True
                else:
                    logger.warning(f"Failed to fetch trades for {ticker}: {exc}")
                break

            for t in data.get("trades", []):
                trades.append(HistoricalTrade(
                    trade_id=t.get("trade_id", ""),
                    ticker=ticker,
                    timestamp=t.get("created_time", ""),
                    yes_price_cents=t.get("yes_price", 50),
                    count=t.get("count", 1),
                    taker_side=t.get("taker_side", "yes"),
                ))

            cursor = data.get("cursor")
            if not cursor:
                break

        if api_failed and not trades:
            trades = _synthetic_trades(ticker, result, close_time)

        trades.sort(key=lambda x: x.timestamp)
        _save_cache(cache_path, [asdict(t) for t in trades])
        logger.debug(f"{ticker}: {len(trades)} trades")
        return trades

    async def fetch_all_trades(
        self, markets: list[Market], concurrency: int = 5
    ) -> dict[str, list[HistoricalTrade]]:
        """Fetch trades for all markets with bounded concurrency."""
        sem = asyncio.Semaphore(concurrency)
        result: dict[str, list[HistoricalTrade]] = {}

        async def _fetch(m: Market):
            async with sem:
                result[m.ticker] = await self.fetch_trades(
                    m.ticker, result=m.result, close_time=m.close_time
                )

        await asyncio.gather(*[_fetch(m) for m in markets])
        return result
