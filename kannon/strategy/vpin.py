"""
VPIN — Volume-Synchronized Probability of Informed Trading.

Reference: Easley, López de Prado & O'Hara (2012)
"Flow Toxicity and Liquidity in a High Frequency World"

Algorithm:
1. Divide trade history into fixed-volume buckets (V* contracts each).
2. Within each bucket classify trades as buy-initiated (B) or sell-initiated (S)
   using the Lee-Ready rule: trade price > mid → buy; ≤ mid → sell.
3. VPIN = mean(|B_i - S_i| / V*) over the last n buckets.
4. VPIN ∈ [0,1]: low = balanced flow (uninformed); high = one-sided (informed).

Empirical thresholds from the Stanford Kalshi study (Bartlett & O'Hara 2026):
  < 0.3  → NORMAL:  quote at standard spread
  0.3–0.6 → CAUTION: widen spread 1.5–2×
  > 0.6  → TOXIC:   cancel all orders immediately
"""
from __future__ import annotations
from collections import deque
from dataclasses import dataclass, field
from enum import Enum


class FlowRegime(str, Enum):
    NORMAL = "normal"
    CAUTION = "caution"
    TOXIC = "toxic"


_CAUTION_THRESHOLD = 0.30
_TOXIC_THRESHOLD = 0.60


@dataclass
class VPINTracker:
    bucket_size: float = 50.0   # V* — contracts per bucket
    n_buckets: int = 50          # lookback window (n in the VPIN formula)

    _bucket_vol: float = field(default=0.0, init=False, repr=False)
    _bucket_buys: float = field(default=0.0, init=False, repr=False)
    _bucket_sells: float = field(default=0.0, init=False, repr=False)
    _imbalances: deque = field(init=False, repr=False)

    def __post_init__(self):
        self._imbalances = deque(maxlen=self.n_buckets)

    def on_trade(self, price_cents: float, size: float, mid_cents: float):
        """
        Process one trade. Lee-Ready classification:
        - price > mid  → buyer-initiated (YES aggressor)
        - price ≤ mid  → seller-initiated (NO aggressor)
        """
        if price_cents > mid_cents:
            self._bucket_buys += size
        else:
            self._bucket_sells += size
        self._bucket_vol += size

        # Close full buckets and carry over the fractional remainder
        while self._bucket_vol >= self.bucket_size:
            fraction = self.bucket_size / self._bucket_vol
            b = self._bucket_buys * fraction
            s = self._bucket_sells * fraction
            # Normalise by V* so imbalance ∈ [0,1]
            self._imbalances.append(abs(b - s) / self.bucket_size)
            self._bucket_vol -= self.bucket_size
            self._bucket_buys *= 1.0 - fraction
            self._bucket_sells *= 1.0 - fraction

    @property
    def value(self) -> float:
        """Current VPIN estimate ∈ [0, 1]."""
        if not self._imbalances:
            return 0.0
        return sum(self._imbalances) / len(self._imbalances)

    @property
    def regime(self) -> FlowRegime:
        v = self.value
        if v >= _TOXIC_THRESHOLD:
            return FlowRegime.TOXIC
        if v >= _CAUTION_THRESHOLD:
            return FlowRegime.CAUTION
        return FlowRegime.NORMAL

    @property
    def has_data(self) -> bool:
        """True once we have enough buckets for a meaningful estimate."""
        return len(self._imbalances) >= 5

    def spread_multiplier(self) -> float:
        """
        Multiplier for the half-spread.
        Returns inf when flow is TOXIC (signal to pull all quotes).
        """
        regime = self.regime
        if regime == FlowRegime.TOXIC:
            return float("inf")
        if regime == FlowRegime.CAUTION:
            # Linear ramp: 1.5× at threshold → 2.0× at TOXIC boundary
            progress = (self.value - _CAUTION_THRESHOLD) / (_TOXIC_THRESHOLD - _CAUTION_THRESHOLD)
            return 1.5 + progress * 0.5
        return 1.0
