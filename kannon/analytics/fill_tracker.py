"""
SQLite-backed order and equity logger.

Writes every placed order to logs/fills.db so you can:
  - Reconstruct P&L at settlement from fill prices + resolution
  - Identify which markets / market types generate alpha vs adverse selection
  - Measure mean reversion vs adverse selection on fill prices

Tables:
  orders            — every limit order placed (not just fills — Kalshi REST
                      doesn't emit a real-time fill notification, so we log
                      placements and compute P&L at settlement)
  equity_snapshots  — periodic mark-to-market snapshots from _sync_positions()

To query P&L after a session (assuming markets are resolved):
  SELECT ticker, side, price_cents, size,
         CASE side WHEN 'bid' THEN (100 - price_cents) * size / 100.0
                   ELSE price_cents * size / 100.0 END AS max_profit
  FROM orders;
"""
from __future__ import annotations
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class FillTracker:
    """Thread-safe (single asyncio thread) SQLite logger."""

    def __init__(self, db_path: str = "logs/fills.db"):
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS orders (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                ts           TEXT    NOT NULL,
                ticker       TEXT    NOT NULL,
                side         TEXT    NOT NULL,
                price_cents  INTEGER NOT NULL,
                size         INTEGER NOT NULL,
                fair_value   REAL,
                ev_dollars   REAL,
                spread_cents INTEGER,
                order_id     TEXT
            );
            CREATE TABLE IF NOT EXISTS equity_snapshots (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                ts         TEXT NOT NULL,
                balance    REAL NOT NULL,
                pos_value  REAL,
                equity     REAL,
                daily_pnl  REAL
            );
            CREATE INDEX IF NOT EXISTS ix_orders_ticker ON orders(ticker);
            CREATE INDEX IF NOT EXISTS ix_orders_ts    ON orders(ts);
        """)
        self._conn.commit()

    # ── Logging methods ───────────────────────────────────────────────────────

    def log_order_placed(
        self,
        ticker: str,
        side: str,
        price_cents: int,
        size: int,
        fair_value: Optional[float] = None,
        ev_dollars: Optional[float] = None,
        spread_cents: Optional[int] = None,
        order_id: Optional[str] = None,
    ):
        """Call this every time an order is successfully placed on the exchange."""
        try:
            self._conn.execute(
                """INSERT INTO orders
                   (ts, ticker, side, price_cents, size, fair_value, ev_dollars, spread_cents, order_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    _now_iso(), ticker, side, price_cents, size,
                    fair_value, ev_dollars, spread_cents, order_id,
                ),
            )
            self._conn.commit()
        except Exception as exc:
            logger.warning(f"FillTracker write failed: {exc}")

    def log_equity_snapshot(
        self,
        balance: float,
        pos_value: float,
        equity: float,
        daily_pnl: float,
    ):
        try:
            self._conn.execute(
                """INSERT INTO equity_snapshots (ts, balance, pos_value, equity, daily_pnl)
                   VALUES (?, ?, ?, ?, ?)""",
                (_now_iso(), balance, pos_value, equity, daily_pnl),
            )
            self._conn.commit()
        except Exception as exc:
            logger.warning(f"FillTracker equity snapshot failed: {exc}")

    # ── Reporting ─────────────────────────────────────────────────────────────

    def session_summary(self) -> list[dict]:
        """
        Per-ticker order summary for the current session (today's UTC date).
        Returns rows: {ticker, bids, asks, avg_bid, avg_ask, net_size}
        """
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        try:
            cur = self._conn.execute(
                """
                SELECT
                    ticker,
                    SUM(CASE WHEN side='bid' THEN 1 ELSE 0 END) AS bids,
                    SUM(CASE WHEN side='ask' THEN 1 ELSE 0 END) AS asks,
                    ROUND(AVG(CASE WHEN side='bid' THEN price_cents END), 1) AS avg_bid,
                    ROUND(AVG(CASE WHEN side='ask' THEN price_cents END), 1) AS avg_ask,
                    SUM(CASE WHEN side='bid' THEN size ELSE -size END) AS net_size
                FROM orders
                WHERE ts LIKE ?
                GROUP BY ticker
                ORDER BY bids + asks DESC
                """,
                (f"{today}%",),
            )
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]
        except Exception as exc:
            logger.warning(f"FillTracker session_summary failed: {exc}")
            return []

    def close(self):
        self._conn.close()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
