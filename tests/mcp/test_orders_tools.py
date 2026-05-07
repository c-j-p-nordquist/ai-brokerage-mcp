from __future__ import annotations

import pytest


def _submit_order_tool():
    from agentic_brokerage_mcp.mcp_server import _register_tools, mcp

    _register_tools()
    return next(t.fn for n, t in mcp._tool_manager._tools.items() if n == "submit_order")


@pytest.mark.asyncio
async def test_manage_order_modify_passes_outside_rth(monkeypatch):
    from agentic_brokerage_mcp.mcp_server import _register_tools, mcp
    from agentic_brokerage_mcp.tools import orders as orders_tools

    _register_tools()

    captured: dict = {}

    class FakeService:
        async def modify(self, *, order_id: str, modifications: dict):
            captured["order_id"] = order_id
            captured["modifications"] = modifications
            return [{"order_id": order_id, **modifications}]

    monkeypatch.setattr(orders_tools, "_svc", lambda: FakeService())

    tool_fn = next(t.fn for n, t in mcp._tool_manager._tools.items() if n == "manage_order")
    await tool_fn(action="modify", order_id="OID-123", outside_rth=True)

    assert captured["order_id"] == "OID-123"
    assert captured["modifications"]["outsideRTH"] is True


@pytest.mark.asyncio
async def test_tool_stp_lmt_missing_stop_price_raises():
    """submit_order tool must reject STP_LMT with no stop_price."""
    tool_fn = _submit_order_tool()

    with pytest.raises(ValueError, match="stop_price"):
        await tool_fn(
            symbol="TSLA",
            side="SELL",
            quantity=3,
            bracket=False,
            order_type="STP_LMT",
            entry_price=345.64,
            stop_price=None,
        )


@pytest.mark.asyncio
async def test_tool_stp_lmt_missing_price_raises():
    """submit_order tool must reject STP_LMT with no limit price."""
    tool_fn = _submit_order_tool()

    with pytest.raises(ValueError, match="limit price"):
        await tool_fn(
            symbol="TSLA",
            side="SELL",
            quantity=3,
            bracket=False,
            order_type="STP_LMT",
            entry_price=None,
            stop_price=346.64,
        )


@pytest.mark.asyncio
async def test_tool_stp_lmt_sell_inverted_stop_raises():
    """STP_LMT SELL: stop_price must be above limit price."""
    tool_fn = _submit_order_tool()

    with pytest.raises(ValueError, match="above limit price"):
        await tool_fn(
            symbol="TSLA",
            side="SELL",
            quantity=3,
            bracket=False,
            order_type="STP_LMT",
            entry_price=346.64,
            stop_price=345.64,
        )


@pytest.mark.asyncio
async def test_tool_stp_lmt_buy_inverted_stop_raises():
    """STP_LMT BUY: stop_price must be below limit price."""
    tool_fn = _submit_order_tool()

    with pytest.raises(ValueError, match="below limit price"):
        await tool_fn(
            symbol="TSLA",
            side="BUY",
            quantity=3,
            bracket=False,
            order_type="STP_LMT",
            entry_price=145.00,
            stop_price=146.00,
        )


def test_mcp_registers_expected_thin_tool_surface():
    from agentic_brokerage_mcp.mcp_server import _register_tools, mcp

    _register_tools()

    assert set(mcp._tool_manager._tools) == {
        "audit",
        "get_option_greeks",
        "ibkr_session",
        "manage_order",
        "manage_watchlist",
        "market",
        "option_chain",
        "portfolio",
        "position_size",
        "search_option_contracts",
        "search_symbol",
        "submit_order",
    }
