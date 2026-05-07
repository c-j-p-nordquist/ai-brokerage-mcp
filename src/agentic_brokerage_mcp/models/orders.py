from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

OrderSide = Literal["BUY", "SELL"]
OrderType = Literal["MKT", "LMT", "STP", "STP_LMT"]


class Order(BaseModel):
    model_config = ConfigDict(extra="forbid")

    side: OrderSide
    qty: float
    order_type: OrderType
    limit_price: float | None = None
    stop_price: float | None = None
    tif: str = "DAY"
    outside_rth: bool = False
    client_order_id: str | None = None
    symbol: str
    conid: str


class BracketOrder(BaseModel):
    model_config = ConfigDict(extra="forbid")

    parent: Order
    stop: Order
    profit: Order | None = None
    oca_group_id: str | None = None


TradeOrder = BracketOrder | Order
