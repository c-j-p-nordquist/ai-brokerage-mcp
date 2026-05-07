from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from agentic_brokerage_mcp.ibkr.market_data import AmbiguousContractError, IBKRMarketDataAdapter
from agentic_brokerage_mcp.ibkr.session import IBKRSessionManager


def _market_data_adapter(payload):
    async def _fake_request(
        method, path, *, params=None, json=None, require_order_serialization=False
    ):
        return payload

    client = MagicMock()
    client.request = _fake_request

    session = MagicMock(spec=IBKRSessionManager)
    session.ensure_session = AsyncMock()
    return IBKRMarketDataAdapter(client, session)


def _queued_market_data_adapter(payloads, captured=None):
    responses = list(payloads)

    async def _fake_request(
        method, path, *, params=None, json=None, require_order_serialization=False
    ):
        if captured is not None:
            captured.append({"method": method, "path": path, "params": params, "json": json})
        if not responses:
            raise AssertionError(f"Unexpected request: {method} {path}")
        return responses.pop(0)

    client = MagicMock()
    client.request = _fake_request

    session = MagicMock(spec=IBKRSessionManager)
    session.ensure_session = AsyncMock()
    return IBKRMarketDataAdapter(client, session)


@pytest.mark.asyncio
async def test_resolve_contract_auto_picks_primary_us_listing():
    adapter = _market_data_adapter(
        [
            {
                "conid": "1001",
                "symbol": "BHP",
                "listingExchange": "NYSE",
                "secType": "STK",
                "description": "BHP Group",
                "currency": "USD",
            },
            {
                "conid": "2002",
                "symbol": "BHP",
                "listingExchange": "ASX",
                "secType": "STK",
                "description": "BHP Group Ltd",
                "currency": "AUD",
            },
        ]
    )

    contract = await adapter.resolve_contract("BHP")

    assert contract.conid == "1001"
    assert contract.exchange == "NYSE"


@pytest.mark.asyncio
async def test_resolve_contract_raises_when_no_unique_primary_us_listing():
    adapter = _market_data_adapter(
        [
            {
                "conid": "1001",
                "symbol": "BHP",
                "listingExchange": "ASX",
                "secType": "STK",
                "description": "BHP Group",
                "currency": "AUD",
            },
            {
                "conid": "2002",
                "symbol": "BHP",
                "listingExchange": "LSE",
                "secType": "STK",
                "description": "BHP Group Ltd",
                "currency": "GBP",
            },
        ]
    )

    with pytest.raises(AmbiguousContractError, match="Pass conid"):
        await adapter.resolve_contract("BHP")


@pytest.mark.asyncio
async def test_resolve_contract_accepts_explicit_conid():
    adapter = _market_data_adapter(
        [
            {
                "conid": "1001",
                "symbol": "BHP",
                "listingExchange": "NYSE",
                "secType": "STK",
                "description": "BHP Group",
                "currency": "USD",
            },
            {
                "conid": "2002",
                "symbol": "BHP",
                "listingExchange": "ASX",
                "secType": "STK",
                "description": "BHP Group Ltd",
                "currency": "AUD",
            },
        ]
    )

    contract = await adapter.resolve_contract("BHP", conid="2002")

    assert contract.conid == "2002"
    assert contract.exchange == "ASX"
    assert contract.currency == "AUD"


@pytest.mark.asyncio
async def test_resolve_contract_hydrates_metadata_for_explicit_conid():
    adapter = _queued_market_data_adapter(
        [
            [
                {
                    "conid": "76792991",
                    "symbol": "TSLA",
                    "listingExchange": "SMART",
                    "secType": "STK",
                    "description": "TESLA INC",
                    "currency": "",
                }
            ],
            {
                "con_id": 76792991,
                "symbol": "TSLA",
                "exchange": "SMART",
                "instrument_type": "STK",
                "company_name": "TESLA INC",
                "currency": "USD",
            },
        ]
    )

    contract = await adapter.resolve_contract("TSLA", conid="76792991")

    assert contract.conid == "76792991"
    assert contract.exchange == "SMART"
    assert contract.currency == "USD"
    assert contract.description == "TESLA INC"


@pytest.mark.asyncio
async def test_get_snapshot_retries_when_first_payload_is_warmup():
    captured = []
    adapter = _queued_market_data_adapter(
        [
            [{"conidEx": "123", "conid": 123}],
            [{"conidEx": "123", "conid": 123, "31": 100.0, "84": 99.5, "86": 100.5}],
        ],
        captured=captured,
    )

    rows = await adapter.get_snapshot(["123"], fields=("31", "84", "86"))

    assert len(captured) == 2
    assert rows[0]["31"] == 100.0


@pytest.mark.asyncio
async def test_resolve_option_underlying_omits_name_param_for_chain_bootstrap():
    captured = []
    adapter = _queued_market_data_adapter(
        [
            [
                {
                    "conid": "12345",
                    "symbol": "MSFT",
                    "listingExchange": "NASDAQ",
                    "secType": "STK",
                    "description": "MICROSOFT CORP",
                    "currency": "USD",
                    "sections": [
                        {"secType": "OPT", "months": "JAN27;FEB27", "exchange": "SMART;CBOE"}
                    ],
                }
            ]
        ],
        captured=captured,
    )

    contract = await adapter.resolve_option_underlying("MSFT")

    assert contract.conid == "12345"
    assert captured[0]["path"] == "/iserver/secdef/search"
    assert captured[0]["params"] == {"symbol": "MSFT"}


@pytest.mark.asyncio
async def test_search_option_contracts_filters_exact_expiry():
    adapter = _queued_market_data_adapter(
        [
            [
                {
                    "conid": "12345",
                    "symbol": "MSFT",
                    "listingExchange": "NASDAQ",
                    "secType": "STK",
                    "description": "MICROSOFT CORP",
                    "currency": "USD",
                    "sections": [{"secType": "OPT", "months": "JAN27", "exchange": "SMART"}],
                }
            ],
            {"call": [400.0], "put": [400.0]},
            [
                {
                    "conid": "900001",
                    "symbol": "MSFT",
                    "exchange": "SMART",
                    "secType": "OPT",
                    "maturityDate": "20270115",
                    "strike": 400.0,
                    "right": "C",
                    "multiplier": "100",
                    "currency": "USD",
                    "undConid": "12345",
                },
                {
                    "conid": "900002",
                    "symbol": "MSFT",
                    "exchange": "SMART",
                    "secType": "OPT",
                    "maturityDate": "20270122",
                    "strike": 400.0,
                    "right": "C",
                    "multiplier": "100",
                    "currency": "USD",
                    "undConid": "12345",
                },
            ],
        ]
    )

    contracts = await adapter.search_option_contracts(
        "MSFT",
        expiry="2027-01-22",
        strike=400.0,
        right="C",
    )

    assert [contract.conid for contract in contracts] == ["900002"]
    assert contracts[0].expiry == "20270122"
