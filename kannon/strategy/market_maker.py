"""
Inventory-aware market making — Avellaneda-Stoikov adapted for binary contracts.

Reference: Avellaneda & Stoikov (2008) "High-Frequency Trading in a Limit Order Book"

Key adaptations for Kalshi prediction markets:
  1. Beta-process volatility: σ_eff(p) = σ_base × √(p(1-p))
     Volatility vanishes as price → 0 or 100 (near-settled market).
  2. Bounded price space: quotes are clipped to [1, 99] cents.
  3. VPIN-aware spread widening: when flow is toxic, we widen or refuse to quote.
  4. Pin-risk protection: T_min prevents spread collapsing near expiry.
  5. Fee-adjusted minimum spread: quotes must clear fees to be EV+.

Spread formula:
  half_spread = γ × σ_eff² × T + (1/γ) × ln(1 + γ/κ)

Reservation price (inventory-adjusted fair value):
  r = fair_value - q × γ × σ_eff² × T

where:
  γ = risk aversion  (higher → wider spread, stronger inventory skew)
  κ = book depth parameter (higher → denser book → narrower spread)
  q = net inventory in YES contracts (+long, -short)
  T = time remaining ∈ [0, 1]
"""
from __future__ import annotations
import math
from dataclasses import dataclass
from typing import Optional

from .fees import FeeConfig, EVCalculator
from .vpin import FlowRegime


@dataclass
class Quote:
    ticker: str
    bid_price: int          # cents [1, 98]
    ask_price: int          # cents [2, 99], always > bid_price
    bid_size: int
    ask_size: int
    fair_value: float
    reservation_price: float
    half_spread: float
    ev_bid: float           # after-fee EV for bid fill (dollars/contract)
    ev_ask: float           # after-fee EV for ask fill (dollars/contract)
    vpin_multiplier: float


class MarketMakerStrategy:
    def __init__(self, cfg: dict, fee_cfg: Optional[FeeConfig] = None):
        self._gamma: float = cfg.get("risk_aversion", 0.1)
        self._kappa: float = cfg.get("order_depth_k", 1.5)
        self._min_half: float = cfg.get("min_half_spread_cents", 1.0)
        self._max_half: float = cfg.get("max_half_spread_cents", 15.0)
        self._target_half: float = cfg.get("target_half_spread_cents", 2.0)
        self._default_size: int = cfg.get("default_size_contracts", 5)
        self._max_pos: int = cfg.get("max_position_contracts", 50)
        self._skew: float = cfg.get("inventory_skew_factor", 0.15)
        self._t_min: float = cfg.get("t_min", 0.05)   # pin-risk floor on T
        self._ev_calc = EVCalculator(fee_cfg or FeeConfig())

    def compute_quote(
        self,
        ticker: str,
        fair_value: float,          # cents [0, 100] from FairValueModel
        sigma_eff: float,           # beta-process vol from FVResult
        position: int,              # net YES contracts
        confidence: float,          # [0, 1] from FVResult
        time_remaining: float = 1.0,
        vpin_regime: FlowRegime = FlowRegime.NORMAL,
        vpin_multiplier: float = 1.0,
    ) -> Optional[Quote]:
        """
        Compute optimal bid/ask given current state.
        Returns None if:
          - fair_value is outside (0, 100) (near-settled / no signal)
          - flow is TOXIC (VPIN says pull all quotes)
          - quotes would not be EV+ after fees
        """
        if not (0.5 < fair_value < 99.5):
            return None

        if vpin_regime == FlowRegime.TOXIC:
            return None

        T = max(self._t_min, time_remaining)
        sigma2 = max(sigma_eff**2, 1e-6)

        # ── Avellaneda-Stoikov half-spread ─────────────────────────────────────
        as_half = (
            self._gamma * sigma2 * T
            + (1.0 / self._gamma) * math.log(1.0 + self._gamma / self._kappa)
        ) * 100.0   # convert to cents (sigma_eff is in [0,1] space)

        # Blend A-S with a target spread, weighted by confidence
        half_spread = confidence * as_half + (1 - confidence) * self._target_half
        half_spread = max(self._min_half, min(self._max_half, half_spread))

        # ── VPIN widening ──────────────────────────────────────────────────────
        half_spread *= vpin_multiplier

        # ── Inventory adjustment ───────────────────────────────────────────────
        pos_ratio = position / self._max_pos
        inv_adj = pos_ratio * self._skew * half_spread * 2.0
        reservation = fair_value - inv_adj

        # ── Quote prices ───────────────────────────────────────────────────────
        bid_f = reservation - half_spread
        ask_f = reservation + half_spread

        bid_price = max(1, min(98, round(bid_f)))
        ask_price = max(bid_price + 2, min(99, round(ask_f)))   # enforce ≥2¢ spread

        # ── Fee-adjusted minimum spread enforcement ────────────────────────────
        # Both sides must be EV+ after fees or we don't quote
        fv_prob = fair_value / 100.0
        ev_bid = self._ev_calc.ev_buy_yes(float(bid_price), fv_prob)
        ev_ask = self._ev_calc.ev_sell_yes(float(ask_price), fv_prob)

        if ev_bid < 0 or ev_ask < 0:
            # Try widening by one cent until both are positive or we hit max spread
            for extra in range(1, 10):
                bp = max(1, bid_price - extra)
                ap = min(99, ask_price + extra)
                ev_bid = self._ev_calc.ev_buy_yes(float(bp), fv_prob)
                ev_ask = self._ev_calc.ev_sell_yes(float(ap), fv_prob)
                if ev_bid >= 0 and ev_ask >= 0:
                    bid_price, ask_price = bp, ap
                    half_spread = (ask_price - bid_price) / 2.0
                    break
            else:
                # Cannot find EV+ quotes at any reasonable spread — don't quote
                return None

        # ── Size skewing ───────────────────────────────────────────────────────
        utilization = abs(position) / self._max_pos
        base = max(1, round(self._default_size * max(0.2, 1.0 - utilization * 0.7)))

        if position > 0:
            bid_size = max(1, round(base * max(0.1, 1.0 - pos_ratio)))
            ask_size = max(1, round(base * (1.0 + pos_ratio * 0.5)))
        elif position < 0:
            bid_size = max(1, round(base * (1.0 + abs(pos_ratio) * 0.5)))
            ask_size = max(1, round(base * max(0.1, 1.0 + pos_ratio)))
        else:
            bid_size = base
            ask_size = base

        return Quote(
            ticker=ticker,
            bid_price=bid_price,
            ask_price=ask_price,
            bid_size=bid_size,
            ask_size=ask_size,
            fair_value=fair_value,
            reservation_price=reservation,
            half_spread=half_spread,
            ev_bid=ev_bid,
            ev_ask=ev_ask,
            vpin_multiplier=vpin_multiplier,
        )
