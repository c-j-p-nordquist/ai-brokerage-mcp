from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from agentic_brokerage_mcp.ibkr.market_data import BarData as AdapterBarData
from agentic_brokerage_mcp.ibkr.market_data import IBKRContract as AdapterIBKRContract
from agentic_brokerage_mcp.ibkr.session import IBKRSessionStatus as AdapterIBKRSessionStatus
from agentic_brokerage_mcp.models import (
    AccountState,
    BarData,
    BracketOrder,
    IBKRContract,
    IBKRSessionStatus,
    Order,
    Position,
)


def test_market_and_session_models_are_reexported_from_adapters() -> None:
    assert AdapterBarData is BarData
    assert AdapterIBKRContract is IBKRContract
    assert AdapterIBKRSessionStatus is IBKRSessionStatus


def test_moved_dataclasses_preserve_existing_construction_behavior() -> None:
    checked_at = datetime(2026, 4, 20, 12, tzinfo=UTC)

    contract = IBKRContract(conid="123", symbol="META", exchange="SMART", asset_class="STK")
    bar = BarData(
        timestamp=checked_at,
        open=1.0,
        high=2.0,
        low=0.5,
        close=1.5,
        volume=1000,
    )
    status = IBKRSessionStatus(
        authenticated=True,
        connected=True,
        competing=False,
        message="ok",
        last_checked_at=checked_at,
    )

    assert contract.currency == ""
    assert contract.option_months == ()
    assert bar.vwap is None
    assert status.sso_expires_ms is None


def test_shared_order_models() -> None:
    parent = Order(
        symbol="META",
        conid="123",
        side="BUY",
        qty=10,
        order_type="LMT",
        limit_price=500.0,
        tif="GTC",
        outside_rth=False,
        client_order_id="proposal-1-parent",
    )
    stop = Order(
        symbol="META",
        conid="123",
        side="SELL",
        qty=10,
        order_type="STP",
        stop_price=470.0,
        client_order_id="proposal-1-stop",
    )
    order = BracketOrder(parent=parent, stop=stop, oca_group_id="proposal-1")

    assert order.parent.limit_price == 500.0
    assert order.stop.stop_price == 470.0
    assert order.oca_group_id == "proposal-1"


def test_account_and_position_models() -> None:
    state = AccountState(
        nlv=100_000,
        cash=30_000,
        buying_power=120_000,
        margin_usage=0.2,
        gross_exposure=90_000,
        open_risk=1_500,
    )
    position = Position(
        symbol="META",
        conid="123",
        qty=10,
        avg_cost=450,
        market_value=5_000,
        unrealized_pnl=500,
        currency="USD",
        asset_class="STK",
    )

    assert state.open_risk == 1_500
    assert position.qty == 10


def test_shared_models_reject_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        Order(
            symbol="META",
            conid="123",
            side="BUY",
            qty=10,
            order_type="LMT",
            unsupported=True,
        )
