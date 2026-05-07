from __future__ import annotations

import pytest

from agentic_brokerage_mcp.ibkr.market_data import IBKRContract
from agentic_brokerage_mcp.services.market_data import MarketDataService


class FakeMarketDataAdapter:
    def __init__(self):
        self.snapshot_calls: list[tuple[list[str], tuple[str, ...]]] = []

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
        return IBKRContract(
            conid=conid or "910001",
            symbol=symbol.upper(),
            exchange=exchange or "SMART",
            asset_class="OPT",
            currency="USD",
            expiry="20270115",
            strike=strike,
            right=right,
            multiplier="100",
            underlying_conid=underlying_conid or "55555",
        )

    async def get_snapshot(
        self,
        conids: list[str],
        *,
        fields: list[str] | tuple[str, ...],
    ) -> list[dict]:
        self.snapshot_calls.append((conids, tuple(fields)))
        if conids == ["910001"]:
            return [
                {
                    "conid": "910001",
                    "31": "12.35",
                    "84": "12.30",
                    "86": "12.40",
                    "6457": "55555",
                    "6509": "RPB",
                    "7089": "1,234",
                    "7283": "28.5%",
                    "7308": "0.42",
                    "7309": "0.018",
                    "7310": "-0.11",
                    "7311": "0.24",
                    "7633": "31.2%",
                    "7635": "12.36",
                    "7638": "456",
                }
            ]
        if conids == ["55555"]:
            return [{"conid": "55555", "31": "C 401.23"}]
        return []


@pytest.mark.asyncio
async def test_option_greeks_parses_snapshot_fields():
    svc = MarketDataService(FakeMarketDataAdapter())

    result = await svc.option_greeks(
        "MSFT",
        expiry="2027-01-15",
        strike=400.0,
        right="C",
    )

    assert result["conid"] == "910001"
    assert result["asset_class"] == "OPT"
    assert result["last_price"] == 12.35
    assert result["mark"] == 12.36
    assert result["delta"] == 0.42
    assert result["gamma"] == 0.018
    assert result["theta"] == -0.11
    assert result["vega"] == 0.24
    assert result["implied_vol_pct"] == 31.2
    assert result["underlying_implied_vol_pct"] == 28.5
    assert result["open_interest"] == 456.0
    assert result["option_volume"] == 1234.0
    assert result["underlying_last_price"] == 401.23
    assert result["market_data_availability"] == "RPB"
    assert result["data_is_delayed"] is False


@pytest.mark.asyncio
async def test_option_greeks_rejects_missing_contract_selectors():
    svc = MarketDataService(FakeMarketDataAdapter())

    with pytest.raises(ValueError, match="expiry, strike, and right"):
        await svc.option_greeks("MSFT")
