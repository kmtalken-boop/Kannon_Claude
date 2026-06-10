"""Rich terminal report for backtest results."""
from __future__ import annotations
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import box

from .engine import MarketResult
from .metrics import BacktestSummary

console = Console()


def _pnl_color(v: float) -> str:
    return f"[green]{v:+.4f}[/green]" if v >= 0 else f"[red]{v:+.4f}[/red]"


def print_market_table(results: list[MarketResult], max_rows: int = 30):
    table = Table(
        title="Per-Market Results",
        box=box.SIMPLE_HEAVY,
        show_lines=False,
    )
    table.add_column("Ticker", style="cyan", max_width=30)
    table.add_column("Res", justify="center")
    table.add_column("Trades", justify="right")
    table.add_column("Fills", justify="right")
    table.add_column("Gross $", justify="right")
    table.add_column("Fees $", justify="right")
    table.add_column("Tax $", justify="right")
    table.add_column("Net $", justify="right")
    table.add_column("Adv%", justify="right")

    sorted_results = sorted(results, key=lambda r: r.net_pnl, reverse=True)

    for r in sorted_results[:max_rows]:
        res_style = "green" if r.resolution == "yes" else "red"
        table.add_row(
            r.ticker,
            f"[{res_style}]{r.resolution.upper()}[/{res_style}]",
            str(r.total_trades),
            str(len(r.fills)),
            f"{r.gross_pnl:+.4f}",
            f"{r.fee_cost:.4f}",
            f"{r.tax_cost:.4f}",
            _pnl_color(r.net_pnl),
            f"{r.adverse_selection_rate*100:.0f}%",
        )

    if len(results) > max_rows:
        table.add_row(f"... {len(results) - max_rows} more ...", *[""] * 8)

    console.print(table)


def print_summary(s: BacktestSummary):
    sharpe_str = f"{s.sharpe_ratio:.2f}" if s.sharpe_ratio is not None else "N/A"

    lines = [
        f"  Markets backtested : {s.total_markets}  ({s.markets_with_fills} had fills)",
        f"  Total trades       : {s.total_trades:,}",
        f"  Total fills        : {s.total_fills:,}  ({s.avg_fill_rate_pct:.1f} fills / 100 trades)",
        "",
        f"  Gross P&L          : ${s.gross_pnl:+.2f}",
        f"  Total fees (7%)    : -${s.total_fees:.2f}",
        f"  Total taxes        : -${s.total_taxes:.2f}",
        f"  [bold]Net P&L            : [/bold]{_pnl_color(s.net_pnl)}",
        f"  Net per fill       : {_pnl_color(s.net_pnl_per_fill)} / contract",
        "",
        f"  Win rate           : {s.win_rate*100:.1f}%  (markets with net profit > 0)",
        f"  Adverse selection  : {s.avg_adverse_selection*100:.1f}%  (fills before price moved against us)",
        f"  Sharpe ratio       : {sharpe_str}  (across markets)",
        f"  Worst market loss  : ${s.max_drawdown:+.2f}  ({s.worst_market})",
        f"  Best market gain   : see {s.best_market}",
    ]

    panel = Panel(
        "\n".join(lines),
        title="[bold green]Backtest Summary[/bold green]",
        border_style="green" if s.net_pnl >= 0 else "red",
        padding=(1, 2),
    )
    console.print(panel)


def print_caveats():
    console.print(
        "\n[dim]Caveats: fill model assumes best-of-book priority (optimistic). "
        "Real fills depend on queue position and market depth. "
        "Use as a directional signal, not an exact P&L forecast.[/dim]\n"
    )
