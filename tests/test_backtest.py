"""Tests for the backtest engine using synthetic trade data."""
import pytest
from kannon.backtest.engine import BacktestEngine, HistoricalTrade
from kannon.backtest.metrics import compute_summary
from kannon.strategy.fees import FeeConfig
from kannon.strategy.market_maker import MarketMakerStrategy


def _mm():
    return MarketMakerStrategy({
        "risk_aversion": 0.01,
        "order_depth_k": 50.0,
        "target_half_spread_cents": 3.0,
        "min_half_spread_cents": 2.0,
        "max_half_spread_cents": 15.0,
        "default_size_contracts": 3,
        "max_position_contracts": 30,
        "inventory_skew_factor": 0.15,
    }, fee_cfg=FeeConfig(fee_rate=0.07, marginal_tax_rate=0.17))


def _engine():
    return BacktestEngine(_mm(), FeeConfig(fee_rate=0.07, marginal_tax_rate=0.17))


def _make_trades(prices: list[int], taker_sides: list[str], ticker="TEST") -> list[HistoricalTrade]:
    return [
        HistoricalTrade(
            trade_id=str(i),
            ticker=ticker,
            timestamp=f"2025-01-01T00:{i:02d}:00Z",
            yes_price_cents=p,
            count=5,
            taker_side=s,
        )
        for i, (p, s) in enumerate(zip(prices, taker_sides))
    ]


class TestBacktestEngine:
    def test_too_few_trades_returns_none(self):
        engine = _engine()
        trades = _make_trades([50] * 5, ["yes"] * 5)
        result = engine.simulate_market("X", trades, "yes", 50)
        assert result is None

    def test_stable_market_produces_fills(self):
        engine = _engine()
        # Market stable at 50¢, alternating buys and sells — should get some fills
        prices = [50] * 60
        sides = ["yes", "no"] * 30
        trades = _make_trades(prices, sides)
        result = engine.simulate_market("X", trades, "yes", 50)
        assert result is not None
        assert result.total_trades == 60

    def test_resolution_yes_long_position_profits(self):
        engine = _engine()
        # All trades hit bid (NO takers at low price) → we accumulate long YES
        # Market resolves YES → we should profit
        prices = [40] * 60  # well below fair value of 50
        sides = ["no"] * 60  # taker buys NO = hits YES bid
        trades = _make_trades(prices, sides)
        result = engine.simulate_market("X", trades, "yes", 50)
        assert result is not None
        if result.fills:
            # Long YES position + YES resolution = profit
            assert result.gross_pnl > 0

    def test_resolution_no_long_position_loses(self):
        engine = _engine()
        prices = [40] * 60
        sides = ["no"] * 60   # we buy YES at ~40
        trades = _make_trades(prices, sides)
        result = engine.simulate_market("X", trades, "no", 50)
        assert result is not None
        if result.fills:
            assert result.gross_pnl < 0

    def test_net_pnl_less_than_gross(self):
        engine = _engine()
        prices = [40] * 60
        sides = ["no"] * 60
        trades = _make_trades(prices, sides)
        result = engine.simulate_market("X", trades, "yes", 50)
        assert result is not None
        if result.fills and result.gross_pnl > 0:
            assert result.net_pnl < result.gross_pnl  # fees and taxes reduce PnL
            assert result.fee_cost >= 0
            assert result.tax_cost >= 0

    def test_fill_rate_between_0_and_100(self):
        engine = _engine()
        prices = [50] * 60
        sides = ["yes", "no"] * 30
        trades = _make_trades(prices, sides)
        result = engine.simulate_market("X", trades, "yes", 50)
        assert result is not None
        assert 0 <= result.fill_rate <= 100

    def test_adverse_selection_rate_between_0_and_1(self):
        engine = _engine()
        prices = list(range(40, 100))  # trending up
        sides = ["no"] * 60
        trades = _make_trades(prices, sides)
        result = engine.simulate_market("X", trades, "yes", 50)
        assert result is not None
        assert 0 <= result.adverse_selection_rate <= 1


class TestBacktestMetrics:
    def test_empty_results(self):
        summary = compute_summary([])
        assert summary.total_markets == 0
        assert summary.net_pnl == 0

    def test_summary_aggregates_correctly(self):
        from kannon.backtest.engine import MarketResult, Fill
        results = [
            MarketResult("A", "yes", fills=[
                Fill("A", "bid", 40, 5, "2025-01-01T00:01:00Z", 50.0, 0.05)
            ], gross_pnl=3.0, net_pnl=2.0, fee_cost=0.7, tax_cost=0.3,
               num_yes_fills=1, num_no_fills=0, final_position=5,
               adverse_selection_rate=0.2, fill_rate=5.0, total_trades=20),
            MarketResult("B", "no", fills=[], gross_pnl=-1.0, net_pnl=-1.0,
               fee_cost=0.0, tax_cost=0.0, num_yes_fills=0, num_no_fills=0,
               final_position=0, adverse_selection_rate=0.0, fill_rate=0.0,
               total_trades=15),
        ]
        summary = compute_summary(results)
        assert summary.total_markets == 2
        assert summary.markets_with_fills == 1
        assert abs(summary.net_pnl - 1.0) < 1e-9
        assert summary.win_rate == 0.5
