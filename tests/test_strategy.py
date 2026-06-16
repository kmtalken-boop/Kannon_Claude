"""Unit tests for fair value and market making logic."""
import pytest
from kannon.api.models import Orderbook, OrderbookLevel
from kannon.strategy.fair_value import FairValueModel
from kannon.strategy.market_maker import MarketMakerStrategy


def _ob(ticker: str, yes_bids: list[tuple], no_bids: list[tuple]) -> Orderbook:
    return Orderbook(
        ticker=ticker,
        yes_bids=[OrderbookLevel(price_cents=p, quantity=q) for p, q in yes_bids],
        no_bids=[OrderbookLevel(price_cents=p, quantity=q) for p, q in no_bids],
    )


class TestFairValue:
    def setup_method(self):
        self.model = FairValueModel({"imbalance_weight": 0.3, "depth_levels": 5})

    def test_symmetric_book_returns_mid(self):
        ob = _ob("X", [(40, 100), (39, 50)], [(60, 100), (61, 50)])
        # best yes bid=40, best yes ask=100-60=40 — wait, 100-60=40 makes spread=0
        # Use: yes_bid=40, no_bid=55 → yes_ask=45
        ob = _ob("X", [(40, 100)], [(55, 100)])
        result = self.model.compute(ob)
        assert result is not None
        assert abs(result.mid - 42.5) < 0.01
        # With equal sizes on each side, imbalance ≈ 0, fair value ≈ mid
        assert abs(result.fair_value - result.mid) < 1.0

    def test_bid_heavy_book_raises_fair_value(self):
        # More bid depth → fair value above mid
        ob = _ob("X", [(45, 500)], [(55, 50)])   # yes_ask = 100-55 = 45 → spread=0
        # Fix: yes_bid=40, no_bid=55 (yes_ask=45), much more bid than ask
        ob = _ob("X", [(40, 500)], [(55, 50)])
        result = self.model.compute(ob)
        assert result is not None
        assert result.fair_value > result.mid

    def test_no_book_returns_fallback(self):
        # Empty book returns a FVResult at 50¢ prior with confidence=0 so the
        # strategy quotes wide (target_half_spread) rather than refusing to quote.
        ob = _ob("X", [], [])
        result = self.model.compute(ob)
        assert result is not None
        assert result.confidence == 0.0
        assert result.fair_value == 50.0

    def test_one_sided_book(self):
        ob = _ob("X", [(50, 100)], [])
        result = self.model.compute(ob)
        assert result is not None
        assert result.fair_value == 50.0


class TestMarketMaker:
    def setup_method(self):
        self.mm = MarketMakerStrategy({
            "risk_aversion": 0.01,
            "order_depth_k": 50.0,
            "target_half_spread_cents": 2.0,
            "min_half_spread_cents": 1.0,
            "max_half_spread_cents": 15.0,
            "default_size_contracts": 5,
            "max_position_contracts": 50,
            "inventory_skew_factor": 0.15,
        })

    def test_zero_inventory_symmetric(self):
        # sigma_eff at p=50%: sqrt(0.5*0.5) = 0.25
        q = self.mm.compute_quote("X", fair_value=50.0, sigma_eff=0.25, position=0, confidence=1.0)
        assert q is not None
        assert q.bid_price < q.ask_price
        # Symmetric quotes around 50¢ with zero inventory
        assert abs((q.bid_price + q.ask_price) / 2 - 50) <= 1

    def test_long_inventory_skews_down(self):
        q_flat = self.mm.compute_quote("X", fair_value=50.0, sigma_eff=0.25, position=0, confidence=1.0)
        q_long = self.mm.compute_quote("X", fair_value=50.0, sigma_eff=0.25, position=30, confidence=1.0)
        assert q_long is not None
        # Reservation price should be lower when long (skewing toward selling)
        assert q_long.reservation_price < q_flat.reservation_price

    def test_quotes_always_in_valid_range(self):
        import math
        for fv in [5, 20, 50, 80, 95]:
            p = fv / 100.0
            sigma_eff = math.sqrt(p * (1 - p))
            for pos in [-40, 0, 40]:
                q = self.mm.compute_quote("X", float(fv), sigma_eff, pos, 0.8)
                if q:
                    assert 1 <= q.bid_price <= 98
                    assert 2 <= q.ask_price <= 99
                    assert q.ask_price > q.bid_price

    def test_no_quote_at_extremes(self):
        assert self.mm.compute_quote("X", 0.0, 0.0, 0, 1.0) is None
        assert self.mm.compute_quote("X", 100.0, 0.0, 0, 1.0) is None
