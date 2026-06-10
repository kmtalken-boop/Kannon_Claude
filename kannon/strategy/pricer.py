"""
Event-type-aware external fair value pricing engines.

These supplement (not replace) the microstructure-based fair value in fair_value.py.
When an external anchor is available (e.g. CME FedWatch for FOMC contracts),
it is blended with the orderbook-derived estimate.

Currently implemented:
  - BinaryBlackScholes: for financial asset outcome contracts
    (e.g. "Will S&P 500 close above 5000 today?")
  - Elo-based sports pricer (stub — plug in your data source)
  - FOMC/CME anchor (stub — plug in cme_probability from FedWatch API)

Reference:
  Carr & Chou (1997) / Black-Scholes (1973): cash-or-nothing call = N(d₂)
  where d₂ = [ln(S/K) + (r - σ²/2)·T] / (σ·√T)
"""
from __future__ import annotations
import math
from dataclasses import dataclass
from typing import Optional


def _ncdf(x: float) -> float:
    """Standard normal CDF via erf approximation."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


@dataclass
class BinaryBlackScholes:
    """
    Cash-or-nothing call: pays $1 if S_T > K.
    Used for financial asset outcome contracts on Kalshi.

    Fair value = N(d₂) × 100 cents.
    """

    def price(
        self,
        spot: float,        # Current underlying price
        strike: float,      # Contract strike (event threshold)
        time_years: float,  # Time to resolution in years (e.g. 0.5/365 = 30 min)
        vol: float,         # Annualised volatility (e.g. 0.20 for VIX ~ 20%)
        rate: float = 0.05,
    ) -> Optional[float]:
        if time_years <= 1e-9 or vol <= 1e-9 or spot <= 0 or strike <= 0:
            return None
        d2 = (math.log(spot / strike) + (rate - 0.5 * vol**2) * time_years) / (
            vol * math.sqrt(time_years)
        )
        return _ncdf(d2) * 100.0   # cents

    def delta_wrt_spot(
        self,
        spot: float,
        strike: float,
        time_years: float,
        vol: float,
        rate: float = 0.05,
    ) -> Optional[float]:
        """Sensitivity of fair value (in cents) per unit change in spot price."""
        if time_years <= 1e-9 or vol <= 1e-9:
            return None
        d2 = (math.log(spot / strike) + (rate - 0.5 * vol**2) * time_years) / (
            vol * math.sqrt(time_years)
        )
        n_prime = math.exp(-0.5 * d2**2) / math.sqrt(2 * math.pi)
        return n_prime / (spot * vol * math.sqrt(time_years)) * 100.0


class EventPricer:
    """
    Routes a market to the appropriate external pricing model.
    Returns a fair value in cents, or None if no anchor is available.
    """

    def __init__(self):
        self._bs = BinaryBlackScholes()

    def price_financial(
        self,
        spot: float,
        strike: float,
        time_years: float,
        vol: float,
        rate: float = 0.05,
    ) -> Optional[float]:
        """Binary BS fair value for 'will asset close above K?' contracts."""
        return self._bs.price(spot, strike, time_years, vol, rate)

    def price_fomc(self, *, cme_probability: float) -> float:
        """
        Anchor to CME FedWatch probability.
        Pull cme_probability from: https://www.cmegroup.com/markets/interest-rates/cme-fedwatch-tool.html
        cme_probability ∈ [0, 1] → return in cents [0, 100].
        """
        return cme_probability * 100.0

    def price_sports_elo(
        self,
        home_elo: float,
        away_elo: float,
        calibration_alpha: float = 0.75,
    ) -> float:
        """
        Elo win probability for home team, calibrated toward 50%.
        calibration_alpha: compress overconfidence (research suggests 0.70–0.85).
        """
        raw_p = 1.0 / (1.0 + 10 ** ((away_elo - home_elo) / 400.0))
        return (0.5 + calibration_alpha * (raw_p - 0.5)) * 100.0

    def blend(
        self,
        external_fv: Optional[float],
        microstructure_fv: float,
        external_weight: float = 0.6,
    ) -> float:
        """
        Blend external anchor with microstructure estimate.
        When external_fv is None, falls back entirely to microstructure.
        """
        if external_fv is None:
            return microstructure_fv
        w = max(0.0, min(1.0, external_weight))
        return w * external_fv + (1 - w) * microstructure_fv
