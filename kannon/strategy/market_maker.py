"""
Quoting logic: inventory-aware market making using the Avellaneda-Stoikov
framework adapted for binary prediction market contracts.

Reference: Avellaneda & Stoikov (2008) "High-frequency trading in a limit
order book", applied to contracts on [0,1] instead of geometric Brownian motion.

Key idea:
  reservation_price = fair_value - q * γ * σ² * T
  half_spread       = γ * σ² * T + (2/γ) * ln(1 + γ/k)

where:
  q   = current inventory (signed, in contracts)
  γ   = risk aversion parameter
  σ²  = variance of the contract price process ≈ p*(1-p) / horizon
  T   = time remaining (normalized)
  k   = order book depth parameter
"""
from __future__ import annotations
import math
from dataclasses import dataclass


@dataclass
class Quote:
    ticker: str
    bid_price: int      # cents (1-99)
    ask_price: int      # cents (1-99), > bid_price
    bid_size: int
    ask_size: int
    fair_value: float
    reservation_price: float
    half_spread: float


class MarketMakerStrategy:
    def __init__(self, cfg: dict):
        self._gamma: float = cfg.get("risk_aversion", 0.1)
        self._k: float = cfg.get("order_depth_k", 1.5)
        self._target_half: float = cfg.get("target_half_spread_cents", 2.0)
        self._min_half: float = cfg.get("min_half_spread_cents", 1.0)
        self._max_half: float = cfg.get("max_half_spread_cents", 15.0)
        self._default_size: int = cfg.get("default_size_contracts", 5)
        self._max_position: int = cfg.get("max_position_contracts", 50)
        self._skew_factor: float = cfg.get("inventory_skew_factor", 0.15)

    def compute_quote(
        self,
        ticker: str,
        fair_value: float,      # cents
        position: int,          # net YES contracts (+ = long)
        volatility: float,      # std dev of mid changes in cents
        confidence: float,      # [0,1]
        time_remaining: float = 1.0,  # normalized [0,1]
    ) -> Quote | None:
        if not (0 < fair_value < 100):
            return None

        p = fair_value / 100.0                      # price in [0,1]
        sigma2 = max(p * (1 - p), 1e-6)             # binary contract variance

        # Avellaneda-Stoikov half-spread
        as_half = (
            self._gamma * sigma2 * time_remaining
            + (2.0 / self._gamma) * math.log(1.0 + self._gamma / self._k)
        ) * 100.0   # scale to cents

        # Blend A-S spread with our target, weighted by confidence
        half_spread = confidence * as_half + (1 - confidence) * self._target_half
        half_spread = max(self._min_half, min(self._max_half, half_spread))

        # Widen spread when local volatility is high (adverse selection protection)
        if volatility > 0.5:
            half_spread = min(self._max_half, half_spread + volatility * 0.5)

        # ── Inventory adjustment ──────────────────────────────────────────────
        # Shift reservation price toward reducing the inventory imbalance
        pos_ratio = position / self._max_position
        inventory_adj = pos_ratio * self._skew_factor * half_spread * 2

        reservation = fair_value - inventory_adj

        bid_f = reservation - half_spread
        ask_f = reservation + half_spread

        bid_price = max(1, min(98, round(bid_f)))
        ask_price = max(bid_price + 1, min(99, round(ask_f)))

        # Ensure minimum spread
        if ask_price - bid_price < 2:
            ask_price = bid_price + 2

        # ── Size skewing ──────────────────────────────────────────────────────
        # Reduce size on the side that increases inventory risk
        utilization = abs(position) / self._max_position
        base = max(1, round(self._default_size * (1.0 - utilization * 0.6)))

        if position > 0:
            # Long: want to sell more, buy less
            bid_size = max(1, round(base * (1 - pos_ratio)))
            ask_size = max(1, round(base * (1 + pos_ratio * 0.5)))
        elif position < 0:
            # Short: want to buy more, sell less
            bid_size = max(1, round(base * (1 + abs(pos_ratio) * 0.5)))
            ask_size = max(1, round(base * (1 - abs(pos_ratio))))
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
        )
