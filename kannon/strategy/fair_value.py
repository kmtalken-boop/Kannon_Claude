"""
Fair value estimation for Kalshi binary contracts.

Method: microstructure-based fair value using order book imbalance.

The weighted mid-price shifts toward the side with greater resting liquidity.
This is a well-known signal in equity market making (Lee & Ready, 1991;
Glosten & Milgrom, 1985) applied to binary contracts.

Fair value in [0, 100] cents.
"""
from __future__ import annotations
import math
from collections import deque
from dataclasses import dataclass, field

from ..api.models import Orderbook


@dataclass
class FVResult:
    fair_value: float           # cents [0, 100]
    confidence: float           # [0, 1] — how much to trust this estimate
    mid: float                  # raw mid price
    imbalance: float            # signed [-1, +1]: positive = bullish pressure
    volatility: float           # local vol estimate (std dev of mid changes)


class FairValueModel:
    """
    Computes fair value from the live order book using:
    1. Size-weighted mid (shifted toward the heavier side)
    2. Volume-at-best pressure (top-of-book imbalance)
    3. Rolling volatility for confidence weighting
    """

    def __init__(self, cfg: dict):
        self._imbalance_weight: float = cfg.get("imbalance_weight", 0.3)
        self._depth_levels: int = cfg.get("depth_levels", 5)
        self._vol_lookback: int = cfg.get("volatility_lookback", 20)
        # Per-ticker rolling mid history for vol estimation
        self._mid_history: dict[str, deque[float]] = {}

    def compute(self, ob: Orderbook) -> FVResult | None:
        bid = ob.best_yes_bid_cents
        ask = ob.best_yes_ask_cents

        if bid is None and ask is None:
            return None
        if bid is None:
            return FVResult(ask, 0.1, ask, 0.0, 0.0)
        if ask is None:
            return FVResult(bid, 0.1, bid, 0.0, 0.0)

        mid = (bid + ask) / 2.0
        half_spread = (ask - bid) / 2.0

        # ── Orderbook imbalance ───────────────────────────────────────────────
        bid_qty = sum(
            lv.quantity for lv in ob.yes_bids[: self._depth_levels]
        )
        ask_qty = sum(
            lv.quantity for lv in ob.no_bids[: self._depth_levels]
        )
        total_qty = bid_qty + ask_qty
        imbalance = (bid_qty - ask_qty) / total_qty if total_qty > 0 else 0.0

        # Shift mid toward the imbalance signal
        fair_value = mid + imbalance * half_spread * self._imbalance_weight

        # ── Rolling volatility ────────────────────────────────────────────────
        ticker = ob.ticker
        if ticker not in self._mid_history:
            self._mid_history[ticker] = deque(maxlen=self._vol_lookback)
        hist = self._mid_history[ticker]
        hist.append(mid)

        vol = 0.0
        if len(hist) >= 4:
            diffs = [abs(hist[i] - hist[i - 1]) for i in range(1, len(hist))]
            vol = sum(diffs) / len(diffs)

        # Confidence: scales with depth and decreases when spread is huge
        depth_score = min(total_qty / 50.0, 1.0)
        spread_penalty = max(0.0, 1.0 - half_spread / 20.0)
        confidence = depth_score * spread_penalty

        fair_value = max(1.0, min(99.0, fair_value))
        return FVResult(
            fair_value=fair_value,
            confidence=confidence,
            mid=mid,
            imbalance=imbalance,
            volatility=vol,
        )
