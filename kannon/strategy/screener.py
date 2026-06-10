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
        self.min_price_cents: float = cfg.get("min_price_cents", 3)
        self.max_active: int = cfg.get("max_markets_active", 10)

    def passes(self, m: Market) -> tuple[bool, str]:
        if m.status.value not in ("open", "active"):
            return False, "not open"
        if m.yes_bid is None or m.yes_ask is None:
            return False, "no quotes"
        if m.volume_24h < self.min_volume_24h:
            return False, f"volume {m.volume_24h} < {self.min_volume_24h}"
        if m.open_interest < self.min_open_interest:
            return False, f"OI {m.open_interest} < {self.min_open_interest}"
        spread = m.yes_ask - m.yes_bid
        if spread < self.min_spread_cents:
            return False, f"spread {spread}¢ < {self.min_spread_cents}¢"
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
        # Spread: more edge per fill (but not so wide the market is illiquid)
        if m.spread is not None:
            s += min(m.spread / 4.0, 3.0) * (1 if m.spread < 20 else 0.5)
        # Prefer mid-range prices — maximum variance, most uncertainty to earn from
        if m.mid_price is not None:
            uncertainty = min(m.mid_price, 100 - m.mid_price) / 50.0
            s += uncertainty * 2.0
        return s

    def select(self, markets: list[Market]) -> list[Market]:
        candidates = []
        rejected = 0
        for m in markets:
            ok, reason = self.passes(m)
            if ok:
                candidates.append((self.score(m), m))
            else:
                rejected += 1

        candidates.sort(reverse=True)
        selected = [m for _, m in candidates[: self.max_active]]
        logger.info(
            f"Screened {len(markets)} markets: {len(selected)} selected, {rejected} rejected"
        )
        return selected
