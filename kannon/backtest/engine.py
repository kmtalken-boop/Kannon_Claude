"""
Backtest simulation engine.

Replays historical trades for each market and simulates what would have happened
if we had been quoting with our market making strategy.

Fill model:
  - We maintain a resting bid and ask at our quoted prices.
  - A trade FILLS our bid  when: taker buys NO (hits YES bid), price ≤ our_bid.
  - A trade FILLS our ask  when: taker buys YES (lifts YES ask), price ≥ our_ask.
  - This is optimistic (assumes we're always at the top of book) but gives a
    realistic upper bound on fill frequency.

Fair value in backtest:
  - No live orderbook available from trade data alone.
  - Use exponential moving average of trade prices as fair value proxy.
  - Bootstrap with first N trades as the initial estimate.

Outcome P&L:
  - Position × (resolution_price - fill_price) - fees - taxes
  - resolution_price = 100 if YES, 0 if NO.
"""
from __future__ import annotations
import math
from dataclasses import dataclass, field
from typing import Optional

from .data import HistoricalTrade
from ..strategy.fees import FeeConfig, EVCalculator
from ..strategy.market_maker import MarketMakerStrategy, Quote


@dataclass
class Fill:
    ticker: str
    side: str               # "bid" (we bought YES) or "ask" (we sold YES)
    price_cents: int
    count: int
    timestamp: str
    fv_at_fill: float       # fair value estimate at time of fill
    ev_at_fill: float       # expected EV at time of fill (dollars)


@dataclass
class MarketResult:
    ticker: str
    resolution: str             # "yes" or "no"
    fills: list[Fill]
    gross_pnl: float            # before fees/taxes
    net_pnl: float              # after fees/taxes
    fee_cost: float
    tax_cost: float
    num_yes_fills: int          # fills on bid side (we bought YES)
    num_no_fills: int           # fills on ask side (we sold YES)
    final_position: int         # contracts carried to settlement
    adverse_selection_rate: float  # fraction of fills where price moved against us
    fill_rate: float            # fills per 100 trades
    total_trades: int


class BacktestEngine:
    """
    Simulates market making P&L on historical trade data.
    """

    # EMA alpha for fair value estimation from trade prices.
    # 0.50 gives a half-life of ~2 trades so FV tracks price with minimal lag.
    # A slow alpha (e.g. 0.05) causes quotes to become stale between trades,
    # inflating the simulated fill rate by 4-6×.
    _FV_ALPHA = 0.50
    # Warm-up trades before we start quoting
    _WARMUP = 20

    def __init__(self, mm_strategy: MarketMakerStrategy, fee_cfg: FeeConfig):
        self._mm = mm_strategy
        self._fee_cfg = fee_cfg
        self._ev = EVCalculator(fee_cfg)

    def simulate_market(
        self,
        ticker: str,
        trades: list[HistoricalTrade],
        resolution: str,            # "yes" or "no"
        last_price_cents: int = 50, # starting fair value seed
    ) -> Optional[MarketResult]:
        if len(trades) < self._WARMUP:
            return None

        resolution_price = 100 if resolution == "yes" else 0
        fills: list[Fill] = []
        position = 0                # net YES contracts
        fv = float(last_price_cents)
        vol_ema = 1.0               # rolling volatility in cents

        # Seed fair value from first WARMUP trades
        for t in trades[: self._WARMUP]:
            fv = self._FV_ALPHA * t.yes_price_cents + (1 - self._FV_ALPHA) * fv

        current_bid: Optional[int] = None
        current_ask: Optional[int] = None

        # Track price for adverse selection measurement
        recent_prices: list[float] = []

        for i, trade in enumerate(trades[self._WARMUP:], start=self._WARMUP):
            # ── Update fair value ─────────────────────────────────────────────
            # Save prior FV before updating so quote/fill decisions use only
            # information available before this trade (no lookahead bias).
            prior_fv = fv
            fv = self._FV_ALPHA * trade.yes_price_cents + (1 - self._FV_ALPHA) * fv
            vol_ema = self._FV_ALPHA * abs(trade.yes_price_cents - prior_fv) + (1 - self._FV_ALPHA) * vol_ema
            recent_prices.append(float(trade.yes_price_cents))
            if len(recent_prices) > 20:
                recent_prices.pop(0)

            # ── Recompute quote (from prior_fv, not updated fv) ───────────────
            p = prior_fv / 100.0
            sigma_eff = math.sqrt(max(p * (1 - p), 1e-6))

            # Clamp position within max_position
            max_pos = self._mm._max_pos
            clamped_pos = max(-max_pos, min(max_pos, position))

            quote = self._mm.compute_quote(
                ticker=ticker,
                fair_value=prior_fv,
                sigma_eff=sigma_eff,
                position=clamped_pos,
                confidence=0.7,
                time_remaining=max(0.05, 1.0 - i / len(trades)),
            )

            if quote:
                current_bid = quote.bid_price
                current_ask = quote.ask_price

            # ── Fill detection ────────────────────────────────────────────────
            if current_bid is not None and current_ask is not None:
                p_cents = trade.yes_price_cents

                if trade.taker_side == "no" and p_cents <= current_bid:
                    # Taker is selling YES (buying NO) → they hit our bid
                    if abs(position) < max_pos:
                        ev_bid = self._ev.ev_buy_yes(float(current_bid), prior_fv / 100.0)
                        fills.append(Fill(
                            ticker=ticker,
                            side="bid",
                            price_cents=current_bid,
                            count=min(trade.count, quote.bid_size if quote else 5),
                            timestamp=trade.timestamp,
                            fv_at_fill=prior_fv,
                            ev_at_fill=ev_bid,
                        ))
                        position += fills[-1].count

                elif trade.taker_side == "yes" and p_cents >= current_ask:
                    # Taker is buying YES → they lift our ask
                    if abs(position) < max_pos:
                        ev_ask = self._ev.ev_sell_yes(float(current_ask), prior_fv / 100.0)
                        fills.append(Fill(
                            ticker=ticker,
                            side="ask",
                            price_cents=current_ask,
                            count=min(trade.count, quote.ask_size if quote else 5),
                            timestamp=trade.timestamp,
                            fv_at_fill=prior_fv,
                            ev_at_fill=ev_ask,
                        ))
                        position -= fills[-1].count

        # ── Compute P&L at resolution ─────────────────────────────────────────
        # Kalshi charges fee_rate × gross_profit on each individual winning fill
        # (assessed per settlement, so per-fill is correct for Kalshi's model).
        # Taxes however are owed on NET after-fee income for the year, not per
        # individual fill. We apply the tax rate to max(0, gross - fee_total)
        # so a market with profitable and unprofitable fills doesn't generate
        # phantom tax on gains that are offset by losses in the same market.
        gross, fee_total = 0.0, 0.0

        for fill in fills:
            fill_price = fill.price_cents / 100.0
            count = fill.count

            if fill.side == "bid":
                gross_profit = (resolution_price / 100.0 - fill_price) * count
            else:
                gross_profit = (fill_price - resolution_price / 100.0) * count

            fee = (
                max(0.0, gross_profit) * self._fee_cfg.fee_rate
                + self._fee_cfg.flat_fee_cents / 100.0 * count
            )
            gross += gross_profit
            fee_total += fee

        after_fee_net = gross - fee_total
        tax_total = max(0.0, after_fee_net) * self._fee_cfg.marginal_tax_rate
        net = after_fee_net - tax_total

        # ── Adverse selection rate ────────────────────────────────────────────
        # Compare future prices vs the FILL PRICE (not vs FV at fill time).
        # A bid fill (we bought at bid_price) is adversely selected when
        # future price falls BELOW bid_price — meaning we overpaid relative
        # to where the market ends up. Comparing vs FV overstates adverse
        # selection because FV-at-fill still reflects the pre-fill price.
        adverse = 0
        for fill in fills:
            fill_idx = next(
                (i for i, t in enumerate(trades) if t.timestamp >= fill.timestamp), None
            )
            if fill_idx is not None and fill_idx + 5 < len(trades):
                future_prices = [trades[fill_idx + j].yes_price_cents for j in range(1, 6)]
                future_mid = sum(future_prices) / len(future_prices)
                if fill.side == "bid" and future_mid < fill.price_cents:
                    adverse += 1
                elif fill.side == "ask" and future_mid > fill.price_cents:
                    adverse += 1

        adv_rate = adverse / len(fills) if fills else 0.0
        fill_rate = len(fills) / max(1, len(trades) - self._WARMUP) * 100

        return MarketResult(
            ticker=ticker,
            resolution=resolution,
            fills=fills,
            gross_pnl=gross,
            net_pnl=net,
            fee_cost=fee_total,
            tax_cost=tax_total,
            num_yes_fills=sum(1 for f in fills if f.side == "bid"),
            num_no_fills=sum(1 for f in fills if f.side == "ask"),
            final_position=position,
            adverse_selection_rate=adv_rate,
            fill_rate=fill_rate,
            total_trades=len(trades),
        )
