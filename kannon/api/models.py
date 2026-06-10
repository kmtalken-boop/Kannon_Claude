from __future__ import annotations
from pydantic import BaseModel, Field, field_validator, model_validator
from typing import Optional
from datetime import datetime
from enum import Enum


class Side(str, Enum):
    YES = "yes"
    NO = "no"


class OrderAction(str, Enum):
    BUY = "buy"
    SELL = "sell"


class OrderType(str, Enum):
    LIMIT = "limit"
    MARKET = "market"


class OrderStatus(str, Enum):
    RESTING = "resting"
    OPEN = "open"           # alias used by some API versions
    PENDING = "pending"
    CANCELLED = "cancelled"
    CANCELED = "canceled"   # alternate spelling
    EXECUTED = "executed"
    FILLED = "filled"       # alias for executed
    PARTIALLY_FILLED = "partially_filled"
    CLOSED = "closed"
    EXPIRED = "expired"


class MarketStatus(str, Enum):
    OPEN = "open"
    ACTIVE = "active"
    CLOSED = "closed"
    SETTLED = "settled"
    FINALIZED = "finalized"


class Market(BaseModel):
    ticker: str
    title: str
    status: MarketStatus
    yes_bid: Optional[int] = None   # cents
    yes_ask: Optional[int] = None   # cents
    last_price: Optional[int] = None
    volume: int = 0
    volume_24h: int = 0
    open_interest: int = 0
    close_time: Optional[datetime] = None
    result: Optional[str] = None
    category: Optional[str] = None

    @model_validator(mode="before")
    @classmethod
    def _remap_fp_fields(cls, data: dict) -> dict:
        """Map the demo API's _dollars/_fp field names to our canonical fields."""
        if not isinstance(data, dict):
            return data

        def _to_cents(v) -> Optional[int]:
            """Probability 0.0–1.0 string → integer cents; None/empty → None."""
            if v is None or v == "":
                return None
            c = int(round(float(v) * 100))
            return c if c > 0 else None

        def _fp_int(v) -> int:
            if v is None or v == "":
                return 0
            return int(float(v))

        if data.get("yes_bid") is None:
            data["yes_bid"] = _to_cents(data.get("yes_bid_dollars"))
        if data.get("yes_ask") is None:
            data["yes_ask"] = _to_cents(data.get("yes_ask_dollars"))
        if not data.get("volume_24h"):
            data["volume_24h"] = _fp_int(data.get("volume_24h_fp"))
        if not data.get("volume"):
            data["volume"] = _fp_int(data.get("volume_fp"))
        if not data.get("open_interest"):
            data["open_interest"] = _fp_int(data.get("open_interest_fp"))
        if data.get("last_price") is None:
            data["last_price"] = _to_cents(data.get("last_price_dollars"))
        return data

    @property
    def mid_price(self) -> Optional[float]:
        if self.yes_bid is not None and self.yes_ask is not None:
            return (self.yes_bid + self.yes_ask) / 2.0
        return None

    @property
    def spread(self) -> Optional[int]:
        if self.yes_bid is not None and self.yes_ask is not None:
            return self.yes_ask - self.yes_bid
        return None


class OrderbookLevel(BaseModel):
    price_cents: float
    quantity: float  # dollar value at this level (from API's _fp suffix)

    @property
    def contracts(self) -> float:
        """Approximate contract count: dollar_value / price_dollars."""
        price_dollars = self.price_cents / 100.0
        if price_dollars <= 0:
            return 0.0
        return self.quantity / price_dollars


class Orderbook(BaseModel):
    ticker: str
    # YES bids sorted best (highest) first
    yes_bids: list[OrderbookLevel] = Field(default_factory=list)
    # NO bids sorted best (highest) first; best_yes_ask = 100 - no_bids[0].price_cents
    no_bids: list[OrderbookLevel] = Field(default_factory=list)

    @property
    def best_yes_bid_cents(self) -> Optional[float]:
        return self.yes_bids[0].price_cents if self.yes_bids else None

    @property
    def best_yes_ask_cents(self) -> Optional[float]:
        if self.no_bids:
            return 100.0 - self.no_bids[0].price_cents
        return None

    @property
    def mid_cents(self) -> Optional[float]:
        bid = self.best_yes_bid_cents
        ask = self.best_yes_ask_cents
        if bid is not None and ask is not None:
            return (bid + ask) / 2.0
        return None

    @property
    def spread_cents(self) -> Optional[float]:
        bid = self.best_yes_bid_cents
        ask = self.best_yes_ask_cents
        if bid is not None and ask is not None:
            return ask - bid
        return None


class Order(BaseModel):
    model_config = {"extra": "ignore"}

    order_id: str = ""
    ticker: str = ""
    side: Optional[Side] = None
    action: Optional[OrderAction] = None
    type: Optional[OrderType] = None
    yes_price: int = 0              # cents
    count: int = 0
    remaining_count: int = 0
    status: Optional[OrderStatus] = None
    created_time: Optional[datetime] = None
    updated_time: Optional[datetime] = None

    @model_validator(mode="before")
    @classmethod
    def _remap_fp_fields(cls, data: dict) -> dict:
        if not isinstance(data, dict):
            return data
        # yes_price_dollars: "0.6500" (probability) → yes_price: 65 (cents)
        if not data.get("yes_price"):
            raw = data.get("yes_price_dollars")
            if raw is not None:
                data["yes_price"] = int(round(float(raw) * 100))
        # API may omit original count; remaining_count equals count on fresh order
        if not data.get("count"):
            rc = data.get("remaining_count_fp") or data.get("remaining_count")
            data["count"] = int(float(rc)) if rc else 0
        # Normalise remaining_count from _fp variant
        if not data.get("remaining_count"):
            raw = data.get("remaining_count_fp")
            if raw is not None:
                data["remaining_count"] = int(float(raw))
        # Coerce unknown status values to a safe fallback
        if data.get("status") and data["status"] not in {s.value for s in OrderStatus}:
            data["status"] = "resting"
        return data


class Position(BaseModel):
    ticker: str
    # Positive = net long YES, negative = net short YES
    market_exposure: int = 0
    fees_paid: float = 0.0
    realized_pnl: float = 0.0


class Balance(BaseModel):
    balance: int = 0            # cents
    payout: int = 0

    @property
    def balance_dollars(self) -> float:
        return self.balance / 100.0
