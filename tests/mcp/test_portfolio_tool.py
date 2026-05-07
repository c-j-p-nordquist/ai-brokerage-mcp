from __future__ import annotations

from unittest.mock import AsyncMock

import pytest


@pytest.mark.asyncio
async def test_portfolio_tool_exposes_excess_liquidity(monkeypatch):
    from agentic_brokerage_mcp.mcp_server import _register_tools, mcp
    from agentic_brokerage_mcp.tools import portfolio as portfolio_tools

    _register_tools()

    class FakeService:
        async def overview(self) -> dict:
            return {
                "positions": [],
                "summary": {
                    "net_liquidation": 100000.0,
                    "total_cash": 20000.0,
                    "buying_power": 50000.0,
                    "excess_liquidity": 35000.0,
                    "fx_rates": {},
                },
            }

    monkeypatch.setattr(portfolio_tools, "_svc", lambda: FakeService())
    monkeypatch.setattr(
        portfolio_tools,
        "_order_svc",
        lambda: AsyncMock(live_orders=AsyncMock(), recent_trades=AsyncMock()),
    )

    tool_fn = next(t.fn for n, t in mcp._tool_manager._tools.items() if n == "portfolio")
    result = await tool_fn(include_history=False)

    assert result["account"]["excess_liquidity"] == 35000.0
