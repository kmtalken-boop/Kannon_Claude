"""
External signal router — converts live market data into FV anchors.

Supported sources (all free, no API key required):
  - Binance WebSocket: real-time BTC and ETH spot prices
  - CME FedWatch: FOMC meeting rate-outcome probabilities (polled every 10 min)

Signals are stored in memory and served synchronously to _on_orderbook().
Stale signals (>5 min old) are silently ignored — the microstructure FV takes over.

To add a new source: add a background task in start() that updates self._spots
or self._fomc_probs, and add a routing rule in get_anchor().
"""
from __future__ import annotations
import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass
from typing import Optional

import httpx
import websockets
import websockets.exceptions

from ..strategy.pricer import BinaryBlackScholes

logger = logging.getLogger(__name__)

# Conservative annualised implied vols per underlying.
# BTC and ETH are realised from ATM options; equities from VIX.
# Tune these to your data — they affect the binary BS anchor price.
_ASSET_VOLS: dict[str, float] = {
    "BTC": 0.80,
    "ETH": 0.90,
    "SOL": 1.00,
    "SPX": 0.18,
    "NDX": 0.22,
    "GOLD": 0.15,
    "OIL": 0.40,
}

# Kalshi ticker prefix → (asset_key, anchor_weight)
# anchor_weight: 0.0 = ignore external, 1.0 = use external only
# 0.55 blends 55% external + 45% microstructure
_PREFIX_MAP: dict[str, tuple[str, float]] = {
    "KXBTC": ("BTC", 0.55),
    "KXETH": ("ETH", 0.55),
    "KXSOL": ("SOL", 0.55),
    "INX":   ("SPX", 0.50),
    "KXINX": ("SPX", 0.50),
    "NDX":   ("NDX", 0.50),
    "KXNDX": ("NDX", 0.50),
}

# FOMC ticker pattern: matches FOMC-*, KXFED-*, FED-*
_FOMC_RE = re.compile(r"^(FOMC|KXFED|FED[-_]|KXFOMC)", re.IGNORECASE)

# Strike parsing: extract the numeric threshold from "KXBTC-25JUL-B95000"
# Matches patterns: -B12345, -T12345, -B12345.67 at end of ticker
_STRIKE_RE = re.compile(r"[-_][BT](\d+(?:\.\d+)?)$", re.IGNORECASE)

# Rate target from FOMC tickers: -T4.25 or -T425
_FOMC_RATE_RE = re.compile(r"[-_]T(\d+(?:\.\d+)?)$", re.IGNORECASE)

# Stale threshold for spot quotes (seconds)
_SPOT_STALE_SECS = 300.0


@dataclass
class _SpotQuote:
    price: float
    ts: float
    source: str = "binance"


class ExternalSignalRouter:
    """
    Runs background tasks to maintain fresh external data.
    Call get_anchor(ticker, t_years) from _on_orderbook() to retrieve
    an optional (price_cents, weight) anchor for FairValueModel.
    """

    def __init__(self, cfg: dict):
        self._cfg = cfg
        self._spots: dict[str, _SpotQuote] = {}   # asset → latest spot
        self._fomc_probs: dict[int, float] = {}   # rate_bp → probability [0,1]
        self._running = False
        self._tasks: list[asyncio.Task] = []
        self._bs = BinaryBlackScholes()

    # ── Public API ────────────────────────────────────────────────────────────

    def get_anchor(
        self,
        ticker: str,
        time_to_expiry_years: float,
    ) -> Optional[tuple[float, float]]:
        """
        Return (anchor_price_cents, weight) or None.
        Called synchronously — must not block.
        """
        upper = ticker.upper()

        for prefix, (asset, weight) in _PREFIX_MAP.items():
            if upper.startswith(prefix):
                return self._price_financial(upper, asset, weight, time_to_expiry_years)

        if _FOMC_RE.match(upper):
            return self._price_fomc(upper)

        return None

    async def start(self):
        self._running = True
        signals_cfg = self._cfg

        if signals_cfg.get("binance", {}).get("enabled", True):
            self._tasks.append(asyncio.create_task(
                self._binance_loop(), name="ext-binance"
            ))
            logger.info("ExternalSignalRouter: Binance WebSocket feed starting")

        if signals_cfg.get("fedwatch", {}).get("enabled", True):
            self._tasks.append(asyncio.create_task(
                self._fedwatch_loop(), name="ext-fedwatch"
            ))
            logger.info("ExternalSignalRouter: CME FedWatch poll starting")

    async def stop(self):
        self._running = False
        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()

    def spot_prices(self) -> dict[str, float]:
        """Current spot prices for display."""
        return {k: v.price for k, v in self._spots.items() if time.time() - v.ts < _SPOT_STALE_SECS}

    # ── Routing helpers ───────────────────────────────────────────────────────

    def _price_financial(
        self,
        ticker: str,
        asset: str,
        weight: float,
        t_years: float,
    ) -> Optional[tuple[float, float]]:
        spot_q = self._spots.get(asset)
        if spot_q is None or time.time() - spot_q.ts > _SPOT_STALE_SECS:
            return None

        m = _STRIKE_RE.search(ticker)
        if not m:
            return None

        strike = float(m.group(1))
        vol = _ASSET_VOLS.get(asset, 0.60)
        t = max(t_years, 1.0 / (365 * 24))   # floor at 1 hour

        anchor = self._bs.price(spot_q.price, strike, t, vol)
        if anchor is None:
            return None
        return (anchor, weight)

    def _price_fomc(self, ticker: str) -> Optional[tuple[float, float]]:
        if not self._fomc_probs:
            return None

        m = _FOMC_RATE_RE.search(ticker)
        if not m:
            return None

        rate_float = float(m.group(1))
        if rate_float > 20.0:
            rate_float /= 100.0    # 425 basis-points format → 4.25%
        rate_bp = round(rate_float * 100)

        prob = self._fomc_probs.get(rate_bp)
        if prob is None:
            return None
        return (prob * 100.0, 0.70)   # FedWatch carries ~70% weight

    # ── Binance WebSocket ─────────────────────────────────────────────────────

    _BINANCE_WS = (
        "wss://stream.binance.com:9443/stream"
        "?streams=btcusdt@miniTicker/ethusdt@miniTicker"
    )
    _BINANCE_ASSET = {"BTCUSDT": "BTC", "ETHUSDT": "ETH"}

    async def _binance_loop(self):
        backoff = 2.0
        while self._running:
            try:
                async with websockets.connect(
                    self._BINANCE_WS,
                    ping_interval=20,
                    ping_timeout=10,
                ) as ws:
                    backoff = 2.0
                    logger.info("Binance WebSocket connected — receiving BTC/ETH prices")
                    async for raw in ws:
                        if not self._running:
                            return
                        try:
                            outer = json.loads(raw)
                            data = outer.get("data", outer)
                            sym = data.get("s", "").upper()
                            close = data.get("c")
                            if close and sym in self._BINANCE_ASSET:
                                asset = self._BINANCE_ASSET[sym]
                                self._spots[asset] = _SpotQuote(
                                    price=float(close), ts=time.time()
                                )
                        except Exception:
                            pass
            except asyncio.CancelledError:
                return
            except (websockets.exceptions.ConnectionClosed, OSError) as exc:
                if not self._running:
                    return
                logger.warning(f"Binance WS disconnected ({exc}), reconnect in {backoff:.0f}s")
                await asyncio.sleep(backoff)
                backoff = min(60.0, backoff * 2)
            except Exception as exc:
                if not self._running:
                    return
                logger.warning(f"Binance WS error: {exc}, reconnect in {backoff:.0f}s")
                await asyncio.sleep(backoff)
                backoff = min(60.0, backoff * 2)

    # ── CME FedWatch ──────────────────────────────────────────────────────────

    _FEDWATCH_URL = (
        "https://www.cmegroup.com/CmeFedWatch/staticData/json/FedWatchOverallProb.json"
    )

    async def _fedwatch_loop(self):
        interval = self._cfg.get("fedwatch", {}).get("poll_interval_seconds", 600)
        # Fetch immediately on startup
        try:
            await self._fetch_fedwatch()
        except Exception as exc:
            logger.warning(f"Initial FedWatch fetch failed: {exc}")

        while self._running:
            await asyncio.sleep(interval)
            if not self._running:
                return
            try:
                await self._fetch_fedwatch()
            except asyncio.CancelledError:
                return
            except Exception as exc:
                logger.warning(f"FedWatch poll error: {exc}")

    async def _fetch_fedwatch(self):
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(self._FEDWATCH_URL)
        if resp.status_code != 200:
            logger.warning(f"FedWatch returned HTTP {resp.status_code}")
            return

        try:
            data = resp.json()
        except Exception as exc:
            logger.warning(f"FedWatch JSON parse error: {exc}")
            return

        # CME structure: {"probabilities": {"JUL2025": {"4.25": 0.312, "4.50": 0.541, ...}, ...}}
        probs_raw = data.get("probabilities", {})
        if not probs_raw:
            logger.debug("FedWatch: no probabilities key in response")
            return

        # Take the first (nearest) meeting
        first_meeting_probs = next(iter(probs_raw.values()), {})
        parsed: dict[int, float] = {}
        for rate_str, prob in first_meeting_probs.items():
            try:
                rate_float = float(rate_str)
                rate_bp = round(rate_float * 100)
                parsed[rate_bp] = float(prob)
            except (ValueError, TypeError):
                continue

        if parsed:
            self._fomc_probs = parsed
            top = max(parsed.items(), key=lambda x: x[1])
            logger.info(
                f"FedWatch updated: {len(parsed)} outcomes, "
                f"most likely = {top[0]/100:.2f}% ({top[1]:.1%})"
            )
