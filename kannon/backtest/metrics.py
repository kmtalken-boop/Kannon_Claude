"""Aggregate performance metrics across all backtested markets."""
from __future__ import annotations
import math
from dataclasses import dataclass
from typing import Optional

from .engine import MarketResult


@dataclass
class BacktestSummary:
    total_markets: int
    markets_with_fills: int
    total_fills: int
    total_trades: int

    gross_pnl: float
    total_fees: float
    total_taxes: float
    net_pnl: float
    net_pnl_per_fill: float

    win_rate: float             # % of markets with net profit > 0
    avg_fill_rate_pct: float    # fills per 100 trades
    avg_adverse_selection: float

    sharpe_ratio: Optional[float]   # of per-market net P&L
    max_drawdown: float             # worst single-market loss
    best_market: str
    worst_market: str


def compute_summary(results: list[MarketResult]) -> BacktestSummary:
    if not results:
        return BacktestSummary(0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, None, 0, "-", "-")

    filled = [r for r in results if r.fills]

    net_pnls = [r.net_pnl for r in results]
    best = max(results, key=lambda r: r.net_pnl)
    worst = min(results, key=lambda r: r.net_pnl)
    total_fills = sum(len(r.fills) for r in results)

    # Sharpe: mean(net_pnl) / std(net_pnl) across markets
    sharpe: Optional[float] = None
    if len(net_pnls) >= 4:
        mean = sum(net_pnls) / len(net_pnls)
        variance = sum((x - mean) ** 2 for x in net_pnls) / len(net_pnls)
        std = math.sqrt(variance)
        sharpe = mean / std if std > 0 else None

    return BacktestSummary(
        total_markets=len(results),
        markets_with_fills=len(filled),
        total_fills=total_fills,
        total_trades=sum(r.total_trades for r in results),
        gross_pnl=sum(r.gross_pnl for r in results),
        total_fees=sum(r.fee_cost for r in results),
        total_taxes=sum(r.tax_cost for r in results),
        net_pnl=sum(r.net_pnl for r in results),
        net_pnl_per_fill=sum(r.net_pnl for r in results) / max(1, total_fills),
        win_rate=sum(1 for r in results if r.net_pnl > 0) / len(results),
        avg_fill_rate_pct=sum(r.fill_rate for r in filled) / max(1, len(filled)),
        avg_adverse_selection=sum(r.adverse_selection_rate for r in filled) / max(1, len(filled)),
        sharpe_ratio=sharpe,
        max_drawdown=min(net_pnls),
        best_market=best.ticker,
        worst_market=worst.ticker,
    )
