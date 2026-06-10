from __future__ import annotations
from pydantic import BaseModel, Field, field_validator
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
    PENDING = "pending"
    CANCELLED = "cancelled"
    EXECUTED = "executed"
    PARTIALLY_FILLED = "partially_filled"


class MarketStatus(str, Enum):
    OPEN = "open"
    CLOSED = "closed"
    SETTLED = "settled"


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
    order_id: str
    ticker: str
    side: Side
    action: OrderAction
    type: OrderType
    yes_price: int              # cents
    count: int
    remaining_count: int = 0
    status: OrderStatus
    created_time: Optional[datetime] = None
    updated_time: Optional[datetime] = None


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
