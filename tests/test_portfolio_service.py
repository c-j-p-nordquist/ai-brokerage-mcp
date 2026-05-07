from __future__ import annotations

import pytest

from agentic_brokerage_mcp.services.portfolio import PortfolioService


class CountingAccountAdapter:
    def __init__(self):
        self.summary_calls = 0
        self.ledger_calls = 0

    async def account_summary(self, account_id: str) -> dict:
        self.summary_calls += 1
        return {
            "net_liquidation": 100000.0,
            "total_cash": 20000.0,
            "buying_power": 50000.0,
            "gross_position_value": 80000.0,
            "excess_liquidity": 35000.0,
        }

    async def account_ledger(self, account_id: str) -> dict:
        self.ledger_calls += 1
        return {
            "USD": {"cashbalance": 8000.0},
            "EUR": {"cashbalance": 12000.0},
        }


class CountingOrderAdapter:
    def __init__(self):
        self.positions_calls = 0

    async def portfolio_positions(self, account_id: str) -> list[dict]:
        self.positions_calls += 1
        return [
            {
                "conid": "12345",
                "contractDesc": "AAPL",
                "position": 10,
                "mktPrice": 150.0,
                "mktValue": 1500.0,
                "avgCost": 140.0,
                "unrealizedPnl": 100.0,
                "realizedPnl": 0.0,
                "currency": "USD",
                "assetClass": "STK",
            }
        ]


@pytest.mark.asyncio
async def test_summary_fetches_account_and_ledger_once():
    account_adapter = CountingAccountAdapter()
    order_adapter = CountingOrderAdapter()
    svc = PortfolioService(
        order_adapter=order_adapter,
        account_adapter=account_adapter,
        account_id="DEMO",
    )

    result = await svc.summary()

    assert result["positions_count"] == 1
    assert account_adapter.summary_calls == 1
    assert account_adapter.ledger_calls == 1
    assert order_adapter.positions_calls == 1


@pytest.mark.asyncio
async def test_overview_reuses_single_remote_snapshot():
    account_adapter = CountingAccountAdapter()
    order_adapter = CountingOrderAdapter()
    svc = PortfolioService(
        order_adapter=order_adapter,
        account_adapter=account_adapter,
        account_id="DEMO",
    )

    result = await svc.overview()

    assert len(result["positions"]) == 1
    assert result["summary"]["positions_count"] == 1
    assert account_adapter.summary_calls == 1
    assert account_adapter.ledger_calls == 1
    assert order_adapter.positions_calls == 1


@pytest.mark.asyncio
async def test_summary_preserves_excess_liquidity():
    account_adapter = CountingAccountAdapter()
    order_adapter = CountingOrderAdapter()
    svc = PortfolioService(
        order_adapter=order_adapter,
        account_adapter=account_adapter,
        account_id="DEMO",
    )

    result = await svc.summary()

    assert result["excess_liquidity"] == 35000.0
