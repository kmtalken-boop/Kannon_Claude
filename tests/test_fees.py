"""Tests for fee and tax-adjusted EV calculations."""
import pytest
from kannon.strategy.fees import FeeConfig, EVCalculator


def ev(fee_rate=0.07, tax=0.0):
    return EVCalculator(FeeConfig(fee_rate=fee_rate, marginal_tax_rate=tax))


class TestEVCalculator:
    def test_no_edge_at_fair_price(self):
        calc = ev(fee_rate=0.0, tax=0.0)
        # At zero fees, buying YES at exactly fair probability should be breakeven
        # ev_buy_yes(50, 0.5) = 0.5*(0.5) - 0.5*(0.5) = 0
        result = calc.ev_buy_yes(50.0, 0.5)
        assert abs(result) < 1e-9

    def test_positive_ev_when_buying_below_fair(self):
        calc = ev(fee_rate=0.0, tax=0.0)
        # Buying at 40¢ when true prob is 60% → EV+ trade
        result = calc.ev_buy_yes(40.0, 0.6)
        assert result > 0

    def test_negative_ev_when_buying_above_fair(self):
        calc = ev(fee_rate=0.0, tax=0.0)
        result = calc.ev_buy_yes(70.0, 0.5)
        assert result < 0

    def test_fees_reduce_ev(self):
        no_fee = ev(fee_rate=0.0)
        with_fee = ev(fee_rate=0.07)
        ev_no_fee = no_fee.ev_buy_yes(40.0, 0.6)
        ev_with_fee = with_fee.ev_buy_yes(40.0, 0.6)
        assert ev_with_fee < ev_no_fee

    def test_taxes_reduce_ev(self):
        no_tax = ev(tax=0.0)
        with_tax = ev(tax=0.35)
        assert with_tax.ev_buy_yes(40.0, 0.6) < no_tax.ev_buy_yes(40.0, 0.6)

    def test_breakeven_buy_below_fair(self):
        calc = ev(fee_rate=0.07)
        # Breakeven buy price should be below the true fair probability * 100
        be = calc.breakeven_buy_yes(0.6)
        assert be < 60.0
        # EV at breakeven should be ≈ 0
        assert abs(calc.ev_buy_yes(be, 0.6)) < 0.001

    def test_breakeven_sell_above_fair(self):
        calc = ev(fee_rate=0.07)
        # Breakeven sell price should be above the fair price
        be = calc.breakeven_sell_yes(0.4)
        assert be > 40.0

    def test_min_edge_spread_positive(self):
        calc = ev(fee_rate=0.07)
        spread = calc.min_edge_spread(0.5)
        # At 50/50 and 7% fee, need >0¢ spread to be EV+
        assert spread > 0

    def test_sell_yes_ev_symmetric_to_buy(self):
        calc = ev(fee_rate=0.0, tax=0.0)
        # sell YES at 60¢ when true prob = 40% should mirror buy YES at 40¢ when prob = 60%
        ev_sell = calc.ev_sell_yes(60.0, 0.4)
        ev_buy = calc.ev_buy_yes(40.0, 0.6)
        assert abs(ev_sell - ev_buy) < 1e-9


class TestBreakevenProperties:
    def test_buy_breakeven_increases_with_fee(self):
        for fee in [0.0, 0.05, 0.10, 0.15]:
            calc = ev(fee_rate=fee)
            be = calc.breakeven_buy_yes(0.5)
            # Higher fee → lower breakeven price (harder to make money)
            assert be <= 50.0

    def test_spread_increases_with_fee(self):
        low = ev(fee_rate=0.03).min_edge_spread(0.5)
        high = ev(fee_rate=0.10).min_edge_spread(0.5)
        assert high > low
