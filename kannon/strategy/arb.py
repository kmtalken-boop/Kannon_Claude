"""
Cross-market arbitrage scanner — within Kalshi.

Detects arbitrage in exhaustive outcome series (mutually exclusive, collectively
exhaustive contracts where exactly one resolves YES):

  sum(ask_prices) < 100¢  →  buy all outcomes and lock in riskless profit
  sum(bid_prices) > 100¢  →  sell all outcomes and lock in riskless profit

Examples:
  FOMC-25JUL-T4.25, FOMC-25JUL-T4.50, FOMC-25JUL-T4.75  (one rate will be chosen)
  CPI-25AUG-G2, CPI-25AUG-G3, CPI-25AUG-G4               (CPI falls in one range)

Ticker convention assumed: everything before the last hyphen segment is the series key.
  "FOMC-25JUL-T4.50"  → series = "FOMC-25JUL"
  "CPI-25AUG-G3"      → series = "CPI-25AUG"

Fee-aware: actual arbitrage profit must clear round-trip fees on ALL legs.
"""
from __future__ import annotations
import logging
from dataclasses import dataclass

from ..api.models import Market
from .fees import FeeConfig, EVCalculator

logger = logging.getLogger(__name__)


@dataclass
class ArbOpportunity:
    series_key: str
    tickers: list[str]
    arb_type: str               # "buy_all" or "sell_all"
    gross_profit_cents: float
    net_profit_cents: float     # after fees on all legs
    description: str


def _series_key(ticker: str) -> str | None:
    """Extract the event series prefix from a Kalshi ticker."""
    parts = ticker.rsplit("-", 1)
    return parts[0] if len(parts) == 2 else None


class ArbScanner:
    def __init__(self, fee_cfg: FeeConfig, min_net_profit_cents: float = 1.5):
        self._ev = EVCalculator(fee_cfg)
        self.min_net = min_net_profit_cents

    def scan(self, markets: list[Market]) -> list[ArbOpportunity]:
        """
        Scan all open markets for exhaustive-series arbitrage.
        Returns a list of actionable opportunities (after fees).
        """
        series: dict[str, list[Market]] = {}
        for m in markets:
            key = _series_key(m.ticker)
            if key:
                series.setdefault(key, []).append(m)

        opportunities = []
        for key, group in series.items():
            if len(group) < 2:
                continue
            opps = self._check_series(key, group)
            opportunities.extend(opps)

        if opportunities:
            for opp in opportunities:
                logger.info(f"ARB: {opp.description}")

        return opportunities

    def _check_series(self, key: str, markets: list[Market]) -> list[ArbOpportunity]:
        # Only consider markets with valid two-sided quotes
        quoted = [m for m in markets if m.yes_bid is not None and m.yes_ask is not None]
        if len(quoted) < 2:
            return []

        # MECE check: for a valid exhaustive series, sum of midpoints should be ≈ 100¢.
        # A sum far above 100 means markets are independent (e.g. "will X attend?")
        # or cumulative thresholds — NOT mutually exclusive, NOT a real arbitrage.
        # Window (50, 160): handles up to ~5 outcomes with ≤20¢ spreads while rejecting
        # attendance/cumulative markets where sum_mids >> 200.
        sum_mids = sum((m.yes_bid + m.yes_ask) / 2.0 for m in quoted)
        if not (50.0 < sum_mids < 160.0):
            return []

        opps = []

        # ── Buy-all arbitrage ─────────────────────────────────────────────────
        total_ask = sum(m.yes_ask for m in quoted)
        if total_ask < 100:
            gross = 100 - total_ask
            # Fee on each leg (buy YES on all outcomes): fee applies on the winning leg
            # Only one leg wins, so total fee ≈ fee_rate × (100 - winning_price_cents) / 100
            # Conservative estimate: assume worst case (lowest price wins = highest fee)
            min_ask = min(m.yes_ask for m in quoted)
            worst_case_fee = self._ev.cfg.fee_rate * (100 - min_ask)
            net = gross - worst_case_fee
            if net >= self.min_net:
                opps.append(ArbOpportunity(
                    series_key=key,
                    tickers=[m.ticker for m in quoted],
                    arb_type="buy_all",
                    gross_profit_cents=float(gross),
                    net_profit_cents=float(net),
                    description=(
                        f"BUY ALL {key}: ask_sum={total_ask}¢ "
                        f"gross={gross:.1f}¢ net={net:.1f}¢"
                    ),
                ))

        # ── Sell-all arbitrage ────────────────────────────────────────────────
        total_bid = sum(m.yes_bid for m in quoted)
        if total_bid > 100:
            gross = total_bid - 100
            # Selling all: one leg pays out $1, fee on winning side's profit
            max_bid = max(m.yes_bid for m in quoted)
            worst_case_fee = self._ev.cfg.fee_rate * max_bid
            net = gross - worst_case_fee
            if net >= self.min_net:
                opps.append(ArbOpportunity(
                    series_key=key,
                    tickers=[m.ticker for m in quoted],
                    arb_type="sell_all",
                    gross_profit_cents=float(gross),
                    net_profit_cents=float(net),
                    description=(
                        f"SELL ALL {key}: bid_sum={total_bid}¢ "
                        f"gross={gross:.1f}¢ net={net:.1f}¢"
                    ),
                ))

        return opps
