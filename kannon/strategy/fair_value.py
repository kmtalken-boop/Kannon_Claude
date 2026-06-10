"""
Fair value estimation for Kalshi binary contracts.

Combines three layers:
1. Microstructure baseline: size-weighted mid with orderbook imbalance adjustment
2. OFI signal: real-time bid/ask pressure from Order Flow Imbalance
3. External anchor (optional): B-S binary, CME FedWatch, Elo, etc.

The beta-process volatility formula σ_eff(p) = σ_base × √(p(1-p)) is applied
throughout — it makes volatility approach zero as the price nears 0 or 100,
which is the correct behaviour for a binary contract nearing resolution.

Reference for imbalance-adjusted mid:
  Lee & Ready (1991); Glosten & Milgrom (1985)
"""
from __future__ import annotations
import math
from collections import deque
from dataclasses import dataclass, field
from typing import Optional

from ..api.models import Orderbook


@dataclass
class FVResult:
    fair_value: float           # cents [0, 100] — use this for quoting
    confidence: float           # [0, 1] — scales spread width
    mid: float                  # raw mid before signals
    imbalance: float            # signed [-1, 1], positive = buy pressure
    volatility_cents: float     # local vol in cents (rolling avg |Δmid|)
    sigma_eff: float            # β-process vol: σ_base × √(p(1-p))
    ofi_adjustment: float       # OFI-derived FV shift in cents
    external_anchor: Optional[float]  # external model price, if available


class FairValueModel:
    def __init__(self, cfg: dict):
        self._imbalance_weight: float = cfg.get("imbalance_weight", 0.3)
        self._depth_levels: int = cfg.get("depth_levels", 5)
        self._vol_lookback: int = cfg.get("volatility_lookback", 20)
        self._sigma_base: float = cfg.get("sigma_base", 1.0)
        # Per-ticker mid history for rolling vol estimation
        self._mid_history: dict[str, deque] = {}
        # Last computed FV per ticker — used as fallback on empty books
        self._last_fv: dict[str, float] = {}

    # ── Public API ────────────────────────────────────────────────────────────

    def compute(
        self,
        ob: Orderbook,
        ofi_adjustment_cents: float = 0.0,
        external_anchor: Optional[float] = None,
        external_weight: float = 0.6,
    ) -> Optional[FVResult]:
        """
        Compute fair value from the live orderbook.

        Args:
            ob: Current orderbook state.
            ofi_adjustment_cents: Signal from OFITracker.update() — added to FV.
            external_anchor: Optional external model price (cents). When provided,
                             it is blended with the microstructure estimate.
            external_weight: Weight on external anchor (0 = ignore, 1 = use only anchor).

        Returns:
            FVResult or None if the book is empty.
        """
        bid = ob.best_yes_bid_cents
        ask = ob.best_yes_ask_cents

        if bid is None and ask is None:
            # Empty book — use last known FV or 50¢ prior; zero confidence so the
            # strategy falls back to its configured target_half_spread_cents.
            fallback = self._last_fv.get(ob.ticker, 50.0)
            return self._empty_book(fallback, ob.ticker)
        if bid is None:
            return self._one_sided(ask, "ask", ob.ticker)
        if ask is None:
            return self._one_sided(bid, "bid", ob.ticker)

        mid = (bid + ask) / 2.0
        half_spread = (ask - bid) / 2.0

        # ── Orderbook imbalance ───────────────────────────────────────────────
        # Use dollar depth (raw quantity from API) for both sides so the comparison
        # is like-for-like. Contract counts create a spurious bias: at 40¢, equal
        # dollar depth yields 2.5 YES contracts vs 1.67 NO contracts, giving a fake
        # bullish signal just because YES is cheaper per contract.
        bid_depth = sum(lv.quantity for lv in ob.yes_bids[: self._depth_levels])
        ask_depth = sum(lv.quantity for lv in ob.no_bids[: self._depth_levels])
        total = bid_depth + ask_depth
        imbalance = (bid_depth - ask_depth) / total if total > 0 else 0.0

        # Shift mid toward the heavier side
        micro_fv = mid + imbalance * half_spread * self._imbalance_weight

        # ── OFI adjustment ────────────────────────────────────────────────────
        micro_fv += ofi_adjustment_cents

        # ── External anchor blend ─────────────────────────────────────────────
        if external_anchor is not None:
            w = max(0.0, min(1.0, external_weight))
            blended_fv = w * external_anchor + (1 - w) * micro_fv
        else:
            blended_fv = micro_fv

        blended_fv = max(1.0, min(99.0, blended_fv))

        # ── Rolling volatility ────────────────────────────────────────────────
        hist = self._mid_history.setdefault(ob.ticker, deque(maxlen=self._vol_lookback))
        hist.append(mid)
        vol = self._rolling_vol(hist)

        # ── Beta-process effective volatility ─────────────────────────────────
        p = blended_fv / 100.0
        sigma_eff = self._sigma_base * math.sqrt(max(p * (1.0 - p), 1e-6))

        # ── Confidence ────────────────────────────────────────────────────────
        depth_score = min(total / 50.0, 1.0)
        spread_penalty = max(0.0, 1.0 - half_spread / 25.0)
        confidence = depth_score * spread_penalty

        self._last_fv[ob.ticker] = blended_fv
        return FVResult(
            fair_value=blended_fv,
            confidence=confidence,
            mid=mid,
            imbalance=imbalance,
            volatility_cents=vol,
            sigma_eff=sigma_eff,
            ofi_adjustment=ofi_adjustment_cents,
            external_anchor=external_anchor,
        )

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _empty_book(self, fv: float, ticker: str) -> FVResult:
        """Zero-information FV when orderbook is empty; confidence=0 → target spread."""
        p = fv / 100.0
        sigma_eff = self._sigma_base * math.sqrt(max(p * (1 - p), 1e-6))
        return FVResult(
            fair_value=fv,
            confidence=0.0,
            mid=fv,
            imbalance=0.0,
            volatility_cents=0.0,
            sigma_eff=sigma_eff,
            ofi_adjustment=0.0,
            external_anchor=None,
        )

    def _one_sided(self, price: float, side: str, ticker: str) -> FVResult:
        # A lone ask at 98¢ or lone bid at 2¢ is usually a stale default order,
        # not a true signal about fair value. Using that price as FV causes the
        # bot to quote at extreme prices (bid 96¢ on a market worth 30¢).
        # Use cached FV from previous two-sided computation, or 50¢ prior.
        fallback = self._last_fv.get(ticker, 50.0)
        return self._empty_book(fallback, ticker)

    @staticmethod
    def _rolling_vol(hist: deque) -> float:
        if len(hist) < 4:
            return 0.0
        diffs = [abs(hist[i] - hist[i - 1]) for i in range(1, len(hist))]
        return sum(diffs) / len(diffs)
