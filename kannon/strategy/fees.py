"""
Fee and tax-adjusted EV calculations for Kalshi contracts.

Kalshi fee structure (as of 2026):
  - Fee is charged on the profit portion of a winning contract.
  - Standard rate: ~7% of gross profit per winning contract.
  - Maker rebates may apply at higher tiers — configurable via fee_rate.
  - Fee for YES buy at price p (cents):
      cost         = p / 100
      gross_profit = (100 - p) / 100   (if YES resolves)
      fee          = gross_profit × fee_rate
      net_profit   = gross_profit × (1 - fee_rate)

Tax treatment (US):
  - Prediction market contracts are currently treated as miscellaneous income
    (not section 1256) — taxed at ordinary income rates, not capital gains.
  - Realised profits are taxable; losses are deductible up to income.
  - Configurable marginal_tax_rate; default 0.0 (let user set their bracket).
  - NOTE: tax treatment can change — verify with a tax professional.

All prices in cents unless noted.
"""
from __future__ import annotations
import math
from dataclasses import dataclass


@dataclass
class FeeConfig:
    fee_rate: float = 0.07          # 7% of gross profit on winning contracts
    marginal_tax_rate: float = 0.0  # Set to your effective rate (e.g. 0.35)
    # Flat per-contract fee in addition to proportional fee (rarely non-zero)
    flat_fee_cents: float = 0.0


class EVCalculator:
    """
    Calculates fee- and tax-adjusted expected value for Kalshi contracts.

    All inputs/outputs in dollar terms unless suffix _cents is used.
    """

    def __init__(self, cfg: FeeConfig):
        self.cfg = cfg

    # ── Core EV formula ───────────────────────────────────────────────────────

    def ev_buy_yes(self, price_cents: float, fair_prob: float) -> float:
        """
        EV of buying 1 YES contract at price_cents given fair probability fair_prob.
        Returns after-fee, after-tax EV in dollars per contract.
        """
        p = price_cents / 100.0
        q = fair_prob           # true probability of YES

        gross_profit_if_yes = 1.0 - p   # per contract
        fee = gross_profit_if_yes * self.cfg.fee_rate + self.cfg.flat_fee_cents / 100.0
        net_profit_if_yes = gross_profit_if_yes - fee

        # Tax: only on the net profit portion
        tax_if_yes = max(0.0, net_profit_if_yes) * self.cfg.marginal_tax_rate
        after_tax_profit = net_profit_if_yes - tax_if_yes

        # If NO: lose the initial cost. Loss may be tax-deductible.
        loss_if_no = -p
        tax_benefit_if_no = min(0.0, loss_if_no) * self.cfg.marginal_tax_rate  # negative tax
        after_tax_loss = loss_if_no - tax_benefit_if_no

        return q * after_tax_profit + (1 - q) * after_tax_loss

    def ev_sell_yes(self, price_cents: float, fair_prob: float) -> float:
        """
        EV of selling 1 YES contract at price_cents (= collecting price, paying $1 if YES).
        Returns after-fee, after-tax EV in dollars per contract.
        """
        p = price_cents / 100.0
        q = fair_prob

        # Selling YES: receive p now, pay $1 if YES (net: p - 1), keep p if NO
        gross_profit_if_no = p
        fee_if_no = gross_profit_if_no * self.cfg.fee_rate + self.cfg.flat_fee_cents / 100.0
        net_profit_if_no = gross_profit_if_no - fee_if_no

        tax_if_no = max(0.0, net_profit_if_no) * self.cfg.marginal_tax_rate
        after_tax_profit_if_no = net_profit_if_no - tax_if_no

        loss_if_yes = -(1.0 - p)
        tax_benefit_if_yes = min(0.0, loss_if_yes) * self.cfg.marginal_tax_rate
        after_tax_loss_if_yes = loss_if_yes - tax_benefit_if_yes

        return (1 - q) * after_tax_profit_if_no + q * after_tax_loss_if_yes

    # ── Breakeven prices ──────────────────────────────────────────────────────

    def breakeven_buy_yes(self, fair_prob: float) -> float:
        """
        Maximum price in cents at which buying YES has non-negative after-fee EV.

        Derived by solving ev_buy_yes(p, q) = 0 for p:
          q × (1-p) × (1-f) × (1-t) = (1-q) × p × (1 + t_benefit_rate)
        """
        q = fair_prob
        f = self.cfg.fee_rate
        t = self.cfg.marginal_tax_rate

        # Simplified: ignore small tax_benefit on loss for clarity
        # q × (1-p) × (1-f) × (1-t) ≥ (1-q) × p
        # solve: p ≤ q(1-f)(1-t) / [q(1-f)(1-t) + (1-q)]
        numerator = q * (1 - f) * (1 - t)
        denominator = numerator + (1 - q)
        if denominator <= 0:
            return 0.0
        return (numerator / denominator) * 100.0

    def breakeven_sell_yes(self, fair_prob: float) -> float:
        """
        Minimum price in cents at which selling YES has non-negative after-fee EV.
        """
        q = fair_prob
        f = self.cfg.fee_rate
        t = self.cfg.marginal_tax_rate

        # (1-q) × p × (1-f) × (1-t) ≥ q × (1-p)
        # p ≥ q / [(1-q)(1-f)(1-t) + q]
        numerator = q
        denominator = (1 - q) * (1 - f) * (1 - t) + q
        if denominator <= 0:
            return 100.0
        return (numerator / denominator) * 100.0

    def min_edge_spread(self, fair_prob: float) -> float:
        """
        Minimum bid-ask spread in cents for the market maker to have positive EV
        on both sides after fees and taxes.
        """
        buy_be = self.breakeven_buy_yes(fair_prob)
        sell_be = self.breakeven_sell_yes(fair_prob)
        return max(0.0, sell_be - buy_be)

    def net_edge(self, bid_cents: float, ask_cents: float, fair_prob: float) -> float:
        """
        Combined EV per round-trip (fill on both bid and ask) in dollars.
        Assumes equal probability of a fill on each side for simplicity.
        """
        ev_b = self.ev_buy_yes(bid_cents, fair_prob)
        ev_a = self.ev_sell_yes(ask_cents, fair_prob)
        return ev_b + ev_a
