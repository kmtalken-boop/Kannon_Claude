"""Risk management: daily loss limits, position limits, halt logic."""
from __future__ import annotations
import logging
from dataclasses import dataclass, field
from datetime import date

logger = logging.getLogger(__name__)


@dataclass
class RiskStatus:
    trading_enabled: bool = True
    halt_reason: str = ""
    daily_pnl: float = 0.0
    daily_start: date = field(default_factory=date.today)
    total_delta: int = 0        # sum of |position| across all markets


class RiskManager:
    def __init__(self, cfg: dict):
        self._max_daily_loss: float = cfg.get("max_daily_loss_dollars", 50.0)
        self._max_per_market: int = cfg.get("max_single_market_contracts", 50)
        self._max_total_delta: int = cfg.get("max_total_delta_contracts", 200)
        self._halt_on_loss: bool = cfg.get("halt_on_daily_loss", True)
        self.status = RiskStatus()

    def check_order(self, ticker: str, size: int, positions: dict[str, int]) -> tuple[bool, str]:
        """Return (ok, reason). Called before placing any order."""
        if not self.status.trading_enabled:
            return False, f"trading halted: {self.status.halt_reason}"

        current = positions.get(ticker, 0)
        new_abs = abs(current + size)
        if new_abs > self._max_per_market:
            return False, f"per-market limit: would reach {new_abs} > {self._max_per_market}"

        new_total = sum(abs(v) for t, v in positions.items() if t != ticker)
        new_total += new_abs
        if new_total > self._max_total_delta:
            return False, f"portfolio delta limit: {new_total} > {self._max_total_delta}"

        return True, ""

    def set_daily_pnl(self, pnl: float):
        """
        Set daily P&L directly from an external mark-to-market equity calculation.
        More accurate than record_pnl() deltas because it captures settlement losses
        that the API's realized_pnl_dollars field omits.
        """
        today = date.today()
        if today != self.status.daily_start:
            self.status.daily_start = today
            self.status.trading_enabled = True
            self.status.halt_reason = ""
        self.status.daily_pnl = pnl
        if self._halt_on_loss and pnl < -self._max_daily_loss:
            if self.status.trading_enabled:
                self.status.trading_enabled = False
                self.status.halt_reason = (
                    f"daily loss limit hit (${-pnl:.2f} > ${self._max_daily_loss:.2f})"
                )
                logger.critical(f"RISK HALT: {self.status.halt_reason}")

    def record_pnl(self, delta: float):
        """Accumulate realized P&L delta. Prefer set_daily_pnl() when equity tracking is available."""
        today = date.today()
        if today != self.status.daily_start:
            self.status.daily_pnl = 0.0
            self.status.daily_start = today
            self.status.trading_enabled = True
            self.status.halt_reason = ""

        self.status.daily_pnl += delta

        if self._halt_on_loss and self.status.daily_pnl < -self._max_daily_loss:
            self.status.trading_enabled = False
            self.status.halt_reason = (
                f"daily loss limit hit (${-self.status.daily_pnl:.2f} "
                f"> ${self._max_daily_loss:.2f})"
            )
            logger.critical(f"RISK HALT: {self.status.halt_reason}")

    def update_delta(self, positions: dict[str, int]):
        self.status.total_delta = sum(abs(v) for v in positions.values())

    @property
    def enabled(self) -> bool:
        return self.status.trading_enabled

    def summary(self) -> dict:
        return {
            "enabled": self.status.trading_enabled,
            "halt_reason": self.status.halt_reason,
            "daily_pnl": round(self.status.daily_pnl, 4),
            "total_delta": self.status.total_delta,
        }
