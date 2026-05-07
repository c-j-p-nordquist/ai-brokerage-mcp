from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from agentic_brokerage_mcp.config import settings
from agentic_brokerage_mcp.models import BarData, IBKRContract, IBKRSessionStatus


def _utcnow() -> datetime:
    return datetime.now(UTC)


_CONTRACTS: dict[str, IBKRContract] = {
    "AAPL": IBKRContract(
        conid="265598",
        symbol="AAPL",
        exchange="NASDAQ",
        asset_class="STK",
        description="Apple Inc.",
        currency="USD",
        option_months=("JAN27", "JUN27"),
        option_exchanges=("SMART", "CBOE"),
        valid_exchanges=("SMART", "NASDAQ"),
    ),
    "MSFT": IBKRContract(
        conid="272093",
        symbol="MSFT",
        exchange="NASDAQ",
        asset_class="STK",
        description="Microsoft Corporation",
        currency="USD",
        option_months=("JAN27", "JUN27"),
        option_exchanges=("SMART", "CBOE"),
        valid_exchanges=("SMART", "NASDAQ"),
    ),
    "SPY": IBKRContract(
        conid="756733",
        symbol="SPY",
        exchange="ARCA",
        asset_class="ETF",
        description="SPDR S&P 500 ETF Trust",
        currency="USD",
        option_months=("JAN27", "JUN27"),
        option_exchanges=("SMART", "CBOE"),
        valid_exchanges=("SMART", "ARCA"),
    ),
}

_OPTION_CONTRACTS: dict[str, IBKRContract] = {
    "MSFT-20270115-400-C": IBKRContract(
        conid="910001",
        symbol="MSFT",
        exchange="SMART",
        asset_class="OPT",
        description="MSFT 15JAN27 400 C",
        currency="USD",
        expiry="20270115",
        strike=400.0,
        right="C",
        multiplier="100",
        trading_class="MSFT",
        underlying_conid="272093",
        valid_exchanges=("SMART", "CBOE"),
    ),
    "AAPL-20270115-220-C": IBKRContract(
        conid="910002",
        symbol="AAPL",
        exchange="SMART",
        asset_class="OPT",
        description="AAPL 15JAN27 220 C",
        currency="USD",
        expiry="20270115",
        strike=220.0,
        right="C",
        multiplier="100",
        trading_class="AAPL",
        underlying_conid="265598",
        valid_exchanges=("SMART", "CBOE"),
    ),
}

_PRICES = {
    "265598": 210.42,
    "272093": 401.23,
    "756733": 512.80,
    "910001": 12.35,
    "910002": 9.80,
}


class MockSessionManager:
    async def ensure_session(self) -> IBKRSessionStatus:
        return self._status()

    async def auth_status(self) -> IBKRSessionStatus:
        return self._status()

    @staticmethod
    def _status() -> IBKRSessionStatus:
        return IBKRSessionStatus(
            authenticated=True,
            connected=True,
            competing=False,
            message="demo mode: no live broker connection",
            last_checked_at=_utcnow(),
            sso_expires_ms=None,
        )


class MockAccountAdapter:
    async def account_summary(self, account_id: str) -> dict[str, Any]:
        return {
            "account_id": account_id or "DEMO",
            "net_liquidation": 100_000.0,
            "total_cash": 52_250.0,
            "available_funds": 50_000.0,
            "buying_power": 200_000.0,
            "gross_position_value": 47_750.0,
            "initial_margin": 15_000.0,
            "maintenance_margin": 11_000.0,
            "excess_liquidity": 41_250.0,
            "base_currency": settings.base_currency,
        }

    async def account_ledger(self, account_id: str) -> dict[str, Any]:
        return {
            settings.base_currency: {"cashbalance": 52_250.0, "exchangeRate": 1.0},
            "USD": {"cashbalance": 52_250.0, "exchangeRate": 1.0},
        }


class MockOrderAdapter:
    def __init__(self) -> None:
        self._orders: dict[str, dict[str, Any]] = {}

    async def submit_order(
        self,
        *,
        account_id: str,
        conid: int,
        side: str,
        order_type: str = "MKT",
        quantity: float,
        price: float | None = None,
        stop_price: float | None = None,
        tif: str = "DAY",
        outside_rth: bool = False,
        client_order_id: str | None = None,
    ) -> dict[str, Any]:
        order_id = f"DEMO-{uuid4().hex[:10]}"
        order = {
            "orderId": order_id,
            "acctId": account_id or "DEMO",
            "conid": str(conid),
            "side": side.upper(),
            "orderType": order_type,
            "quantity": quantity,
            "remainingQuantity": quantity,
            "price": price,
            "auxPrice": stop_price,
            "tif": tif,
            "outsideRTH": outside_rth,
            "cOID": client_order_id,
            "status": "Simulated",
        }
        self._orders[order_id] = order
        return {
            "order_id": order_id,
            "status": "Simulated",
            "raw": [{**order, "order_status": "Simulated"}],
        }

    async def submit_bracket_order(
        self,
        *,
        account_id: str,
        conid: int,
        side: str,
        quantity: float,
        entry_price: float,
        stop_price: float,
        target_price: float | None = None,
        tif: str = "DAY",
        outside_rth: bool = False,
        client_order_id: str | None = None,
    ) -> dict[str, Any]:
        parent_id = f"DEMO-BRK-{uuid4().hex[:8]}"
        child_ids = [f"{parent_id}-STP"]
        if target_price is not None:
            child_ids.append(f"{parent_id}-LMT")
        self._orders[parent_id] = {
            "orderId": parent_id,
            "acctId": account_id or "DEMO",
            "conid": str(conid),
            "side": side.upper(),
            "orderType": "LMT",
            "quantity": quantity,
            "remainingQuantity": quantity,
            "price": entry_price,
            "tif": tif,
            "outsideRTH": outside_rth,
            "cOID": client_order_id,
            "status": "Simulated",
        }
        return {
            "parent_order_id": parent_id,
            "child_order_ids": child_ids,
            "status": "Simulated",
            "raw": [
                {"order_id": parent_id, "order_status": "Simulated"},
                *({"order_id": child_id, "order_status": "Simulated"} for child_id in child_ids),
            ],
        }

    async def modify_order(
        self,
        *,
        account_id: str,
        order_id: str,
        modifications: dict[str, Any],
    ) -> list[dict[str, Any]]:
        current = self._orders.setdefault(
            order_id,
            {"orderId": order_id, "acctId": account_id or "DEMO", "status": "Simulated"},
        )
        current.update(modifications)
        return [current]

    async def cancel_order(self, *, account_id: str, order_id: str) -> dict[str, Any]:
        current = self._orders.setdefault(
            order_id,
            {"orderId": order_id, "acctId": account_id or "DEMO"},
        )
        current["status"] = "Cancelled"
        return {"cancelled": True, "order_id": order_id, "status": "Cancelled"}

    async def live_orders(self) -> dict[str, Any]:
        return {"orders": list(self._orders.values())}

    async def portfolio_positions(self, account_id: str) -> list[dict[str, Any]]:
        return [
            {
                "conid": "265598",
                "contractDesc": "AAPL",
                "position": 120,
                "mktPrice": 210.42,
                "mktValue": 25_250.4,
                "avgCost": 185.1,
                "unrealizedPnl": 3_038.4,
                "realizedPnl": 0.0,
                "currency": "USD",
                "assetClass": "STK",
            },
            {
                "conid": "272093",
                "contractDesc": "MSFT",
                "position": 56,
                "mktPrice": 401.23,
                "mktValue": 22_468.88,
                "avgCost": 350.0,
                "unrealizedPnl": 2_868.88,
                "realizedPnl": 0.0,
                "currency": "USD",
                "assetClass": "STK",
            },
        ]

    async def recent_trades(self) -> list[dict[str, Any]]:
        return [
            {
                "symbol": "AAPL",
                "side": "BUY",
                "quantity": 10,
                "price": 208.0,
                "timestamp": (_utcnow() - timedelta(days=2)).isoformat(),
                "execution_id": "DEMO-FILL-1",
            }
        ]


class MockMarketDataAdapter:
    async def search_contracts(
        self,
        query: str,
        sec_type: str | None = "STK",
        *,
        name: bool | None = True,
    ) -> list[IBKRContract]:
        normalized = query.upper()
        contracts = list(_CONTRACTS.values())
        if sec_type:
            contracts = [c for c in contracts if c.asset_class.upper() == sec_type.upper()]
        return [
            contract
            for contract in contracts
            if normalized in contract.symbol.upper() or normalized in contract.description.upper()
        ]

    async def resolve_contract(
        self,
        symbol: str,
        sec_type: str = "STK",
        *,
        conid: str | None = None,
    ) -> IBKRContract:
        if conid:
            for contract in [*_CONTRACTS.values(), *_OPTION_CONTRACTS.values()]:
                if contract.conid == str(conid):
                    return contract
        contract = _CONTRACTS.get(symbol.upper())
        if not contract:
            raise RuntimeError(f"No demo contract found for {symbol}")
        if sec_type and contract.asset_class.upper() != sec_type.upper():
            raise RuntimeError(f"No demo {sec_type} contract found for {symbol}")
        return contract

    async def resolve_option_underlying(
        self,
        symbol: str,
        *,
        underlying_conid: str | None = None,
    ) -> IBKRContract:
        contract = await self.resolve_contract(symbol, conid=underlying_conid)
        if not contract.option_months:
            raise RuntimeError(f"No demo option chain available for {symbol}")
        return contract

    async def get_option_strikes(
        self,
        *,
        underlying_conid: str,
        month: str,
        exchange: str | None = None,
        sec_type: str = "OPT",
    ) -> dict[str, list[float]]:
        calls = [
            contract.strike
            for contract in _OPTION_CONTRACTS.values()
            if contract.underlying_conid == str(underlying_conid)
            and contract.expiry.startswith(_month_to_yyyymm(month))
            and contract.right == "C"
            and contract.strike is not None
        ]
        puts = [
            contract.strike
            for contract in _OPTION_CONTRACTS.values()
            if contract.underlying_conid == str(underlying_conid)
            and contract.expiry.startswith(_month_to_yyyymm(month))
            and contract.right == "P"
            and contract.strike is not None
        ]
        return {"call": sorted(calls or [180.0, 200.0, 220.0, 400.0]), "put": sorted(puts)}

    async def get_option_contracts(
        self,
        *,
        underlying_conid: str,
        month: str,
        strike: float,
        right: str,
        exchange: str | None = None,
        sec_type: str = "OPT",
    ) -> list[IBKRContract]:
        prefix = _month_to_yyyymm(month)
        return [
            contract
            for contract in _OPTION_CONTRACTS.values()
            if contract.underlying_conid == str(underlying_conid)
            and contract.expiry.startswith(prefix)
            and contract.strike == strike
            and contract.right == right.upper()
        ]

    async def search_option_contracts(
        self,
        symbol: str,
        *,
        expiry: str,
        strike: float,
        right: str,
        exchange: str | None = None,
        underlying_conid: str | None = None,
        sec_type: str = "OPT",
    ) -> list[IBKRContract]:
        underlying = await self.resolve_option_underlying(symbol, underlying_conid=underlying_conid)
        normalized_expiry = expiry.replace("-", "")
        return [
            contract
            for contract in _OPTION_CONTRACTS.values()
            if contract.underlying_conid == underlying.conid
            and contract.expiry == normalized_expiry
            and contract.strike == strike
            and contract.right == right.upper()
        ]

    async def resolve_option_contract(
        self,
        symbol: str,
        *,
        expiry: str,
        strike: float,
        right: str,
        exchange: str | None = None,
        underlying_conid: str | None = None,
        conid: str | None = None,
        sec_type: str = "OPT",
    ) -> IBKRContract:
        if conid:
            for contract in _OPTION_CONTRACTS.values():
                if contract.conid == str(conid):
                    return contract
        contracts = await self.search_option_contracts(
            symbol,
            expiry=expiry,
            strike=strike,
            right=right,
            exchange=exchange,
            underlying_conid=underlying_conid,
            sec_type=sec_type,
        )
        if not contracts:
            raise RuntimeError(
                f"No demo option contract found for {symbol} {expiry} {strike} {right}"
            )
        return contracts[0]

    async def get_quotes(self, conids: list[str]) -> list[dict[str, Any]]:
        return await self.get_snapshot(conids, fields=("31", "84", "86"))

    async def get_snapshot(
        self,
        conids: list[str],
        *,
        fields: list[str] | tuple[str, ...],
    ) -> list[dict[str, Any]]:
        rows = []
        for conid in conids:
            price = _PRICES.get(str(conid), 100.0)
            rows.append(
                {
                    "conid": str(conid),
                    "31": price,
                    "84": round(price - 0.05, 2),
                    "86": round(price + 0.05, 2),
                    "6457": "272093" if str(conid) == "910001" else "",
                    "6509": "RPB",
                    "7089": "1234",
                    "7283": "28.5%",
                    "7308": "0.42",
                    "7309": "0.018",
                    "7310": "-0.11",
                    "7311": "0.24",
                    "7633": "31.2%",
                    "7635": price,
                    "7638": "456",
                }
            )
        return rows

    async def get_historical_bars(
        self,
        *,
        conid: str,
        period: str = "1M",
        bar: str = "1d",
        outside_rth: bool = False,
    ) -> list[BarData]:
        base = _PRICES.get(str(conid), 100.0)
        now = _utcnow()
        bars = []
        for index in range(90):
            drift = index * 0.12
            wave = math.sin(index / 6) * 2.2
            close = base - 10 + drift + wave
            bars.append(
                BarData(
                    timestamp=now - timedelta(days=90 - index),
                    open=round(close - 0.4, 2),
                    high=round(close + 1.3, 2),
                    low=round(close - 1.6, 2),
                    close=round(close, 2),
                    volume=1_000_000 + index * 1000,
                )
            )
        return bars

    async def get_news_headlines(self, conid: str, *, count: int = 20) -> list[dict[str, Any]]:
        return [
            {
                "id": "demo-news-1",
                "headline": "Demo market brief: large-cap technology shares trade mixed",
                "source": "demo",
                "published_at": (_utcnow() - timedelta(hours=3)).isoformat(),
            }
        ][:count]

    async def get_news_article(self, article_id: str) -> dict[str, Any]:
        return {
            "id": article_id,
            "headline": "Demo market brief",
            "text": "Synthetic demo article used for local MCP exploration.",
        }

    async def get_contract_info(self, conid: str) -> dict[str, Any]:
        for contract in [*_CONTRACTS.values(), *_OPTION_CONTRACTS.values()]:
            if contract.conid == str(conid):
                return {
                    "con_id": contract.conid,
                    "symbol": contract.symbol,
                    "exchange": contract.exchange,
                    "instrument_type": contract.asset_class,
                    "company_name": contract.description,
                    "currency": contract.currency,
                    "expiry_full": contract.expiry,
                    "strike": contract.strike,
                    "putOrCall": contract.right,
                    "multiplier": contract.multiplier,
                    "underlying_con_id": contract.underlying_conid,
                    "valid_exchanges": ";".join(contract.valid_exchanges),
                }
        return {}


def _month_to_yyyymm(month: str) -> str:
    normalized = month.strip().upper()
    parsed = datetime.strptime(normalized, "%b%y").replace(tzinfo=UTC)
    return parsed.strftime("%Y%m")
