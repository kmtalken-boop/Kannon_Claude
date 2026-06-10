"""Market screening: filter and rank Kalshi markets for market making suitability."""
from __future__ import annotations
import logging
from datetime import datetime, timezone

from ..api.models import Market

logger = logging.getLogger(__name__)


class MarketScreener:
    def __init__(self, cfg: dict):
        self.min_volume_24h: int = cfg.get("min_volume_24h", 100)
        self.min_open_interest: int = cfg.get("min_open_interest", 50)
        self.max_days_to_expiry: float = cfg.get("max_time_to_expiry_days", 30)
        self.min_spread_cents: int = cfg.get("min_spread_cents", 2)
        self.max_spread_cents: int = cfg.get("max_spread_cents", 20)
        self.min_price_cents: float = cfg.get("min_price_cents", 3)
        self.max_active: int = cfg.get("max_markets_active", 10)
        self.excluded_prefixes: list[str] = cfg.get("excluded_ticker_prefixes", [])

    def passes(self, m: Market) -> tuple[bool, str]:
        if m.status.value not in ("open", "active"):
            return False, "not open"
        for prefix in self.excluded_prefixes:
            if m.ticker.startswith(prefix):
                return False, f"excluded prefix ({prefix})"
        if m.yes_bid is None or m.yes_ask is None:
            return False, "no quotes"
        if m.volume_24h < self.min_volume_24h:
            return False, f"volume {m.volume_24h} < {self.min_volume_24h}"
        if m.open_interest < self.min_open_interest:
            return False, f"OI {m.open_interest} < {self.min_open_interest}"
        spread = m.yes_ask - m.yes_bid
        if spread < self.min_spread_cents:
            return False, f"spread {spread}¢ < {self.min_spread_cents}¢"
        if spread > self.max_spread_cents:
            return False, f"spread too wide ({spread}¢ > {self.max_spread_cents}¢)"
        mid = m.mid_price
        if mid is not None:
            distance = min(mid, 100 - mid)
            if distance < self.min_price_cents:
                return False, f"near-settled (mid={mid:.1f}¢)"
        if m.close_time:
            now = datetime.now(timezone.utc)
            days_left = (m.close_time - now).total_seconds() / 86400
            if days_left <= 0:
                return False, "expired"
            if days_left > self.max_days_to_expiry:
                return False, f"too far out ({days_left:.0f}d)"
        return True, ""

    def score(self, m: Market) -> float:
        """Higher score = better market making candidate."""
        s = 0.0
        # Volume: more flow = more fills
        s += min(m.volume_24h / 500.0, 4.0)
        # Open interest: depth of existing market
        s += min(m.open_interest / 200.0, 3.0)
        # Spread: prefer tight external spreads — they indicate an active, price-discovered
        # market. Wide spreads mean uncertain/illiquid markets where adverse selection is high.
        if m.spread is not None:
            s += max(0.0, 3.0 - abs(m.spread - 6) / 4.0)  # peaks at 6¢, falls off
        # Prefer mid-range prices — maximum variance, most uncertainty to earn from
        if m.mid_price is not None:
            uncertainty = min(m.mid_price, 100 - m.mid_price) / 50.0
            s += uncertainty * 2.0
        return s

    def select(self, markets: list[Market]) -> list[Market]:
        candidates = []
        rejection_counts: dict[str, int] = {}
        for m in markets:
            ok, reason = self.passes(m)
            if ok:
                candidates.append((self.score(m), m))
            else:
                rejection_counts[reason] = rejection_counts.get(reason, 0) + 1
                logger.debug(f"REJECT {m.ticker}: {reason}")

        candidates.sort(key=lambda x: x[0], reverse=True)
        selected = [m for _, m in candidates[: self.max_active]]

        # Summarise rejection reasons at INFO level for observability
        total_rejected = sum(rejection_counts.values())
        top_reasons = sorted(rejection_counts.items(), key=lambda x: -x[1])[:4]
        reasons_str = ", ".join(f"{r}×{n}" for r, n in top_reasons)
        logger.info(
            f"Screened {len(markets)}: {len(selected)} selected, "
            f"{total_rejected} rejected ({reasons_str})"
        )
        return selected
