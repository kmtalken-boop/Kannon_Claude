"""
Order Flow Imbalance (OFI) — real-time fair value adjustment signal.

Reference: Cont, Kukanov & Stoikov (2014)
"The Price Impact of Order Book Events" — Journal of Financial Econometrics.

OFI_t = ΔV^bid_t - ΔV^ask_t

where ΔV^bid / ΔV^ask are signed changes in best-level quantities:
  - Bid replenished (+) → bullish pressure → FV shifts up
  - Bid depleted (-)    → bearish pressure → FV shifts down
  - Ask replenished (+) → bearish pressure → FV shifts down
  - Ask depleted (-)    → bullish pressure → FV shifts up

Empirical result: Δmid ≈ β × OFI  (R² ≈ 65% in equity markets)

β is calibrated per market. Default starts conservative; online learning adapts it.
"""
from __future__ import annotations
from collections import deque
from dataclasses import dataclass, field
from typing import Optional

from ..api.models import Orderbook


@dataclass
class OFITracker:
    beta: float = 0.002         # cents per unit OFI — calibrated empirically
    ema_alpha: float = 0.10     # EMA smoothing factor (lower = slower response)
    max_adjustment_cents: float = 5.0   # clamp OFI signal to ±this many cents

    _prev_bid: Optional[float] = field(default=None, init=False, repr=False)
    _prev_bid_qty: float = field(default=0.0, init=False, repr=False)
    _prev_ask: Optional[float] = field(default=None, init=False, repr=False)
    _prev_ask_qty: float = field(default=0.0, init=False, repr=False)
    _ema: float = field(default=0.0, init=False, repr=False)
    _raw_history: deque = field(init=False, repr=False)

    def __post_init__(self):
        self._raw_history = deque(maxlen=100)

    def update(self, ob: Orderbook) -> float:
        """
        Process an orderbook snapshot/update.
        Returns the estimated fair value adjustment in cents (positive = bullish).
        """
        bid = ob.best_yes_bid_cents
        ask = ob.best_yes_ask_cents
        bid_qty = ob.yes_bids[0].quantity if ob.yes_bids else 0.0
        ask_qty = ob.no_bids[0].quantity if ob.no_bids else 0.0

        if self._prev_bid is None:
            # First tick — initialise state, emit no signal
            self._prev_bid = bid
            self._prev_bid_qty = bid_qty
            self._prev_ask = ask
            self._prev_ask_qty = ask_qty
            return 0.0

        raw = self._raw_ofi(bid, bid_qty, ask, ask_qty)
        self._raw_history.append(raw)
        self._ema = self.ema_alpha * raw + (1 - self.ema_alpha) * self._ema

        self._prev_bid = bid
        self._prev_bid_qty = bid_qty
        self._prev_ask = ask
        self._prev_ask_qty = ask_qty

        adjustment = self._ema * self.beta
        return max(-self.max_adjustment_cents, min(self.max_adjustment_cents, adjustment))

    def _raw_ofi(
        self,
        bid: Optional[float], bid_qty: float,
        ask: Optional[float], ask_qty: float,
    ) -> float:
        """Cont et al. definition of instantaneous OFI."""
        bid_term = 0.0
        ask_term = 0.0

        if bid is not None and self._prev_bid is not None:
            if bid > self._prev_bid:
                bid_term = bid_qty
            elif bid == self._prev_bid:
                bid_term = bid_qty - self._prev_bid_qty
            else:
                bid_term = -self._prev_bid_qty

        if ask is not None and self._prev_ask is not None:
            if ask < self._prev_ask:
                ask_term = ask_qty
            elif ask == self._prev_ask:
                ask_term = ask_qty - self._prev_ask_qty
            else:
                ask_term = -self._prev_ask_qty

        return bid_term - ask_term

    @property
    def signal(self) -> float:
        """Current EMA-smoothed OFI value (pre-β scaling)."""
        return self._ema

    def reset(self):
        self._prev_bid = None
        self._prev_bid_qty = 0.0
        self._prev_ask = None
        self._prev_ask_qty = 0.0
        self._ema = 0.0
