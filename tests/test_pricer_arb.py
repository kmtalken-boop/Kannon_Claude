"""Tests for external pricers and arb scanner."""
import pytest
from kannon.strategy.pricer import BinaryBlackScholes, EventPricer
from kannon.strategy.arb import ArbScanner
from kannon.strategy.fees import FeeConfig
from kannon.api.models import Market, MarketStatus


def _market(ticker, bid, ask, volume=500, oi=100):
    return Market(
        ticker=ticker,
        title=ticker,
        status=MarketStatus.OPEN,
        yes_bid=bid,
        yes_ask=ask,
        volume_24h=volume,
        open_interest=oi,
    )


class TestBinaryBS:
    def setup_method(self):
        self.bs = BinaryBlackScholes()

    def test_atm_price_near_50(self):
        p = self.bs.price(spot=100, strike=100, time_years=1/12, vol=0.2)
        # ATM ~ 50¢ but slightly less due to time value
        assert 40 < p < 60

    def test_deep_itm_near_100(self):
        p = self.bs.price(spot=200, strike=100, time_years=1/12, vol=0.2)
        assert p > 90

    def test_deep_otm_near_0(self):
        p = self.bs.price(spot=50, strike=100, time_years=1/12, vol=0.2)
        assert p < 10

    def test_near_expiry_binary(self):
        p_itm = self.bs.price(spot=105, strike=100, time_years=1e-4, vol=0.2)
        p_otm = self.bs.price(spot=95, strike=100, time_years=1e-4, vol=0.2)
        assert p_itm > 80
        assert p_otm < 20

    def test_invalid_inputs_return_none(self):
        assert self.bs.price(0, 100, 0.1, 0.2) is None
        assert self.bs.price(100, 100, 0.0, 0.2) is None
        assert self.bs.price(100, 100, 0.1, 0.0) is None

    def test_delta_positive_for_call(self):
        d = self.bs.delta_wrt_spot(100, 100, 1/12, 0.2)
        assert d > 0


class TestEventPricer:
    def test_blend_with_anchor(self):
        pricer = EventPricer()
        result = pricer.blend(external_fv=60.0, microstructure_fv=50.0, external_weight=0.5)
        assert result == 55.0

    def test_blend_no_anchor_returns_micro(self):
        pricer = EventPricer()
        result = pricer.blend(None, 50.0, 0.6)
        assert result == 50.0

    def test_fomc_passthrough(self):
        pricer = EventPricer()
        assert pricer.price_fomc(cme_probability=0.75) == 75.0

    def test_sports_elo_calibrated(self):
        pricer = EventPricer()
        # Equal teams → 50%
        p = pricer.price_sports_elo(1500, 1500)
        assert abs(p - 50.0) < 0.01
        # Home team heavily favoured → > 50% but calibration should compress it
        p_fav = pricer.price_sports_elo(2000, 1000)
        assert 50 < p_fav < 95


class TestArbScanner:
    def setup_method(self):
        self.scanner = ArbScanner(FeeConfig(fee_rate=0.07), min_net_profit_cents=0.5)

    def test_buy_all_arb_detected(self):
        markets = [
            _market("FOMC-25JUL-T4.25", bid=20, ask=25),
            _market("FOMC-25JUL-T4.50", bid=30, ask=35),
            _market("FOMC-25JUL-T4.75", bid=15, ask=20),
            # Sum of asks = 80¢ < 100¢ → buy all arb
        ]
        opps = self.scanner.scan(markets)
        buy_opps = [o for o in opps if o.arb_type == "buy_all"]
        assert len(buy_opps) >= 1
        assert buy_opps[0].gross_profit_cents == 20.0  # 100 - 80

    def test_no_arb_when_sum_is_fair(self):
        markets = [
            _market("FOMC-25JUL-T4.25", bid=25, ask=35),
            _market("FOMC-25JUL-T4.50", bid=35, ask=45),
            _market("FOMC-25JUL-T4.75", bid=20, ask=25),
            # Sum of asks = 105, sum of bids = 80 → no arb
        ]
        opps = self.scanner.scan(markets)
        assert len(opps) == 0

    def test_sell_all_arb_detected(self):
        markets = [
            _market("CPI-25AUG-G1", bid=40, ask=50),
            _market("CPI-25AUG-G2", bid=40, ask=50),
            _market("CPI-25AUG-G3", bid=40, ask=50),
            # Sum of bids = 120 > 100 → sell all arb
        ]
        opps = self.scanner.scan(markets)
        sell_opps = [o for o in opps if o.arb_type == "sell_all"]
        assert len(sell_opps) >= 1

    def test_single_market_group_ignored(self):
        markets = [_market("SOLO-25JUL-T1", bid=40, ask=50)]
        assert self.scanner.scan(markets) == []

    def test_arb_after_fees_must_exceed_min(self):
        # Tiny gross profit that fees eat entirely
        markets = [
            _market("EVT-25JUL-A", bid=48, ask=49),
            _market("EVT-25JUL-B", bid=48, ask=49),
            _market("EVT-25JUL-C", bid=48, ask=49),
            # Sum of asks = 147 > 100, but sell arb gross = 44¢
            # After fees on winning leg (0.07 × 48) ≈ 3.36¢ → should still show
        ]
        opps = self.scanner.scan(markets)
        sell_opps = [o for o in opps if o.arb_type == "sell_all"]
        if sell_opps:
            assert sell_opps[0].net_profit_cents >= 0.5
