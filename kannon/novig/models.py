"""Data models for the Novig EV betting bot."""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel


class NovigOrderStatus(str, Enum):
    PENDING = "pending"
    PARTIAL = "partial"
    FILLED = "filled"
    CANCELLED = "cancelled"
    CANCELED = "canceled"
    EXPIRED = "expired"


class MarketType(str, Enum):
    H2H = "h2h"
    SPREADS = "spreads"
    TOTALS = "totals"


@dataclass
class EventFairValue:
    """Devvigged fair-value estimates for all outcomes in one event."""
    event_id_odds_api: str
    home_team: str
    away_team: str
    sport: str
    commence_time: datetime
    outcomes: dict[str, float]       # outcome_name -> true probability [0, 1]
    source_books: list[str]
    fetched_at: datetime = field(default_factory=lambda: datetime.utcnow())


@dataclass
class NovigEvent:
    """An event available for betting on Novig."""
    event_id: str
    home_team: str
    away_team: str
    sport: str
    commence_time: datetime
    status: str = "upcoming"


@dataclass
class NovigOffer:
    """A single resting make-bet offer in the Novig order book."""
    offer_id: str
    outcome: str
    american_odds: int
    stake_usd: float
    is_ours: bool = False


@dataclass
class NovigOrderbook:
    """All resting offers for one outcome, sorted best-odds-for-bettor first."""
    event_id: str
    outcome: str
    # sorted: lowest implied probability (= best decimal odds) first
    offers: list[NovigOffer]

    @property
    def best_odds(self) -> Optional[int]:
        return self.offers[0].american_odds if self.offers else None

    def is_our_order_top(self, our_order_id: str) -> bool:
        """
        True if our order is at the best (or tied-for-best) odds level.
        Being undercut means someone else is offering better odds and
        all takers will hit them first.
        """
        if not self.offers:
            return True
        our_offer = next((o for o in self.offers if o.offer_id == our_order_id), None)
        if our_offer is None:
            return False
        from .devig import american_to_implied
        best_implied = american_to_implied(self.offers[0].american_odds)
        our_implied = american_to_implied(our_offer.american_odds)
        return our_implied <= best_implied + 0.002  # tiny tolerance for rounding


class NovigOrder(BaseModel):
    """An order placed on Novig (persisted for monitoring)."""
    model_config = {"extra": "ignore"}

    order_id: str
    event_id: str
    outcome: str
    american_odds: int
    stake_usd: float
    status: NovigOrderStatus = NovigOrderStatus.PENDING
    created_at: Optional[datetime] = None

    # Populated locally after placement — not from the API
    true_prob_at_placement: float = 0.0
    ev_at_placement: float = 0.0
    odds_api_event_id: str = ""


@dataclass
class EVOpportunity:
    """A detected +EV make-bet opportunity."""
    odds_api_event_id: str
    novig_event_id: str
    outcome: str
    true_prob: float
    novig_odds: int        # American odds we will post
    ev_pct: float          # e.g. 0.08 means 8% EV
    stake_usd: float
