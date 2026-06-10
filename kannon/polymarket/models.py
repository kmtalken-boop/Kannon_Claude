"""Pydantic models for the Polymarket US API."""
from __future__ import annotations
from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, model_validator

from ..api.models import Market as KalshiMarket, MarketStatus, Orderbook, OrderbookLevel


class PMMarketState(str, Enum):
    OPEN = "MARKET_STATE_OPEN"
    CLOSED = "MARKET_STATE_CLOSED"
    RESOLVED = "MARKET_STATE_RESOLVED"


class PMOrderIntent(str, Enum):
    BUY_LONG = "ORDER_INTENT_BUY_LONG"    # buy YES
    SELL_LONG = "ORDER_INTENT_SELL_LONG"   # sell YES (close long)
    BUY_SHORT = "ORDER_INTENT_BUY_SHORT"   # buy NO
    SELL_SHORT = "ORDER_INTENT_SELL_SHORT" # sell NO (close short)


class PMOrderType(str, Enum):
    LIMIT = "ORDER_TYPE_LIMIT"
    MARKET = "ORDER_TYPE_MARKET"


class PMTIF(str, Enum):
    GTC = "TIME_IN_FORCE_GOOD_TILL_CANCEL"
    IOC = "TIME_IN_FORCE_IMMEDIATE_OR_CANCEL"
    FOK = "TIME_IN_FORCE_FILL_OR_KILL"
    GTD = "TIME_IN_FORCE_GOOD_TILL_DATE"


class PMOrderStatus(str, Enum):
    OPEN = "ORDER_STATUS_OPEN"
    FILLED = "ORDER_STATUS_FILLED"
    CANCELLED = "ORDER_STATUS_CANCELLED"
    PARTIALLY_FILLED = "ORDER_STATUS_PARTIALLY_FILLED"


class PMPrice(BaseModel):
    value: str       # decimal string e.g. "0.55"
    currency: str = "USD"

    @property
    def cents(self) -> float:
        return float(self.value) * 100.0

    @property
    def prob(self) -> float:
        return float(self.value)


class PMMarket(BaseModel):
    """A single binary outcome market on Polymarket US."""
    slug: str
    title: str
    state: PMMarketState = PMMarketState.OPEN
    close_time: Optional[datetime] = None
    tick_size: float = 0.01
    volume_24h: float = 0.0
    open_interest: float = 0.0
    best_bid: Optional[PMPrice] = None
    best_ask: Optional[PMPrice] = None

    def to_kalshi_market(self) -> KalshiMarket:
        """Convert to the common Market model the screener/strategy expects."""
        yes_bid = round(self.best_bid.cents) if self.best_bid else None
        yes_ask = round(self.best_ask.cents) if self.best_ask else None
        return KalshiMarket(
            ticker=self.slug,
            title=self.title,
            status=MarketStatus.OPEN if self.state == PMMarketState.OPEN else MarketStatus.CLOSED,
            yes_bid=yes_bid,
            yes_ask=yes_ask,
            volume_24h=int(self.volume_24h),
            open_interest=int(self.open_interest),
            close_time=self.close_time,
        )


class PMOrder(BaseModel):
    order_id: str
    market_slug: str
    intent: PMOrderIntent
    order_type: PMOrderType
    price: PMPrice
    quantity: float
    filled_quantity: float = 0.0
    status: PMOrderStatus = PMOrderStatus.OPEN
    created_time: Optional[datetime] = None


class PMPosition(BaseModel):
    market_slug: str
    net_position: float = 0.0    # positive = net long YES, negative = net short YES
    realized_pnl: float = 0.0


class PMBalance(BaseModel):
    available: float = 0.0       # USDC available to trade
    total: float = 0.0

    @property
    def balance_dollars(self) -> float:
        return self.available


def parse_orderbook(slug: str, bids_raw: list, offers_raw: list) -> Orderbook:
    """
    Convert Polymarket US orderbook data to the shared Orderbook model.

    Polymarket gives bids/offers in YES price terms with qty in shares.
    We convert to the Kalshi-compatible Orderbook convention:
      yes_bids  — bids to buy YES, price in YES cents
      no_bids   — mapped from YES asks; price in NO cents (= 100 - yes_ask_cents)

    To preserve the existing OrderbookLevel.contracts property:
      quantity stored = shares × own_price (dollar value at that level)
      → contracts = quantity / price_dollars = shares ✓
    """
    yes_bids: list[OrderbookLevel] = []
    for b in bids_raw:
        p_yes = float(b["px"]["value"])
        qty = float(b["qty"])
        yes_bids.append(OrderbookLevel(
            price_cents=p_yes * 100.0,
            quantity=qty * p_yes,  # dollar value
        ))
    yes_bids.sort(key=lambda lv: lv.price_cents, reverse=True)

    # offers = YES asks → map to no_bids convention (NO price = 1 - yes_ask_price)
    no_bids: list[OrderbookLevel] = []
    for o in offers_raw:
        p_yes = float(o["px"]["value"])
        p_no = 1.0 - p_yes
        qty = float(o["qty"])
        no_bids.append(OrderbookLevel(
            price_cents=p_no * 100.0,
            quantity=qty * p_no,  # dollar value at NO price
        ))
    no_bids.sort(key=lambda lv: lv.price_cents, reverse=True)

    return Orderbook(ticker=slug, yes_bids=yes_bids, no_bids=no_bids)
