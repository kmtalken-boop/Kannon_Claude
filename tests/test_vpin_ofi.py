"""Tests for VPIN and OFI trackers."""
import pytest
from kannon.strategy.vpin import VPINTracker, FlowRegime
from kannon.strategy.ofi import OFITracker
from kannon.api.models import Orderbook, OrderbookLevel


def _ob(yes_bids, no_bids, ticker="X"):
    return Orderbook(
        ticker=ticker,
        yes_bids=[OrderbookLevel(price_cents=p, quantity=q) for p, q in yes_bids],
        no_bids=[OrderbookLevel(price_cents=p, quantity=q) for p, q in no_bids],
    )


class TestVPIN:
    def test_no_data_returns_zero(self):
        v = VPINTracker(bucket_size=10.0, n_buckets=5)
        assert v.value == 0.0
        assert v.regime == FlowRegime.NORMAL

    def test_balanced_flow_low_vpin(self):
        v = VPINTracker(bucket_size=10.0, n_buckets=50)
        mid = 50.0
        for _ in range(200):
            v.on_trade(51.0, 1.0, mid)   # buy
            v.on_trade(49.0, 1.0, mid)   # sell
        assert v.value < 0.3
        assert v.regime == FlowRegime.NORMAL

    def test_one_sided_buy_flow_high_vpin(self):
        v = VPINTracker(bucket_size=10.0, n_buckets=50)
        mid = 50.0
        for _ in range(200):
            v.on_trade(55.0, 1.0, mid)   # all buys
        assert v.value > 0.6
        assert v.regime == FlowRegime.TOXIC

    def test_caution_regime_spreads_multiplier(self):
        v = VPINTracker(bucket_size=10.0, n_buckets=50)
        mid = 50.0
        # Drive to caution zone: ~70% buys
        for _ in range(140):
            v.on_trade(55.0, 1.0, mid)
        for _ in range(60):
            v.on_trade(45.0, 1.0, mid)
        if v.regime == FlowRegime.CAUTION:
            assert 1.0 < v.spread_multiplier() < float("inf")

    def test_toxic_regime_returns_inf_multiplier(self):
        v = VPINTracker(bucket_size=10.0, n_buckets=50)
        mid = 50.0
        for _ in range(300):
            v.on_trade(60.0, 1.0, mid)
        assert v.spread_multiplier() == float("inf")

    def test_has_data_false_before_enough_buckets(self):
        v = VPINTracker(bucket_size=100.0, n_buckets=5)
        v.on_trade(50.0, 1.0, 50.0)   # nowhere near one full bucket
        assert not v.has_data


class TestOFI:
    def test_first_update_returns_zero(self):
        tracker = OFITracker()
        ob = _ob([(40, 100)], [(55, 100)])
        assert tracker.update(ob) == 0.0

    def test_bid_replenishment_positive_signal(self):
        tracker = OFITracker(beta=1.0, ema_alpha=1.0)  # beta=1 and no smoothing
        ob1 = _ob([(40, 100)], [(55, 100)])
        ob2 = _ob([(40, 200)], [(55, 100)])   # bid grew
        tracker.update(ob1)
        adj = tracker.update(ob2)
        assert adj > 0

    def test_ask_replenishment_negative_signal(self):
        tracker = OFITracker(beta=1.0, ema_alpha=1.0)
        ob1 = _ob([(40, 100)], [(55, 100)])
        ob2 = _ob([(40, 100)], [(55, 200)])   # ask grew
        tracker.update(ob1)
        adj = tracker.update(ob2)
        assert adj < 0

    def test_adjustment_clamped_to_max(self):
        tracker = OFITracker(beta=100.0, max_adjustment_cents=5.0)
        ob1 = _ob([(40, 1)], [(55, 1)])
        ob2 = _ob([(40, 10000)], [(55, 1)])
        tracker.update(ob1)
        adj = tracker.update(ob2)
        assert abs(adj) <= 5.0
