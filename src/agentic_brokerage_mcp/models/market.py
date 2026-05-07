from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True)
class IBKRContract:
    conid: str
    symbol: str
    exchange: str
    asset_class: str
    description: str = ""
    currency: str = ""
    expiry: str = ""
    strike: float | None = None
    right: str = ""
    multiplier: str = ""
    trading_class: str = ""
    underlying_conid: str = ""
    option_months: tuple[str, ...] = ()
    option_exchanges: tuple[str, ...] = ()
    valid_exchanges: tuple[str, ...] = ()


@dataclass(slots=True)
class BarData:
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    vwap: float | None = None
