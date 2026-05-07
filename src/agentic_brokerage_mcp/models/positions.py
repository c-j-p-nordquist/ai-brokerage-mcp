from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class Position(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: str
    conid: str
    qty: float
    avg_cost: float
    market_value: float
    unrealized_pnl: float
    currency: str
    asset_class: str
