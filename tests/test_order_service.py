from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from agentic_brokerage_mcp.ibkr.market_data import BarData, IBKRContract
from agentic_brokerage_mcp.services.order_service import OrderService


class FakeMarketDataAdapter:
    async def resolve_contract(
        self,
        symbol: str,
        sec_type: str = "STK",
        *,
        conid: str | None = None,
    ) -> IBKRContract:
        return IBKRContract(
            conid=conid or "12345",
            symbol=symbol.upper(),
            exchange="SMART",
            asset_class="STK",
            currency="USD",
        )

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
            asset_class=sec_type,
            currency="USD",
            expiry="20270115",
            strike=strike,
            right=right,
            multiplier="100",
            underlying_conid=underlying_conid or "55555",
        )

    async def get_quotes(self, conids: list[str]) -> list[dict]:
        price = 12.5 if conids[0] == "910001" else 150.0
        return [{"conid": conids[0], "31": price}]

    async def get_historical_bars(
        self,
        *,
        conid: str,
        period: str = "1M",
        bar: str = "1d",
        outside_rth: bool = False,
    ) -> list[BarData]:
        now = datetime.now(UTC)
        return [
            BarData(
                timestamp=now - timedelta(days=1),
                open=149.0,
                high=151.0,
                low=148.0,
                close=150.0,
                volume=1_000_000,
            )
        ]


class FakeAccountAdapter:
    async def account_summary(self, account_id: str) -> dict:
        return {
            "net_liquidation": 100000.0,
            "total_cash": 25000.0,
            "gross_position_value": 30000.0,
        }


class FakeOrderAdapter:
    def __init__(self):
        self.submit_order_calls = 0
        self.submit_bracket_calls = 0
        self.last_submit_order_kwargs = None
        self.last_submit_bracket_kwargs = None

    async def submit_order(self, **kwargs) -> dict:
        self.submit_order_calls += 1
        self.last_submit_order_kwargs = kwargs
        return {
            "order_id": "OID-1",
            "status": "Submitted",
            "raw": [{"order_id": "OID-1", "order_status": "Submitted"}],
        }

    async def submit_bracket_order(self, **kwargs) -> dict:
        self.submit_bracket_calls += 1
        self.last_submit_bracket_kwargs = kwargs
        return {
            "parent_order_id": "BRK-1",
            "child_order_ids": ["BRK-2", "BRK-3"],
            "status": "Submitted",
            "raw": [{"order_id": "BRK-1", "order_status": "Submitted"}],
        }

    async def live_orders(self) -> dict:
        return {
            "orders": [
                {
                    "orderId": "LIVE-1",
                    "ticker": "AAPL",
                    "side": "BUY",
                    "remainingQuantity": 5,
                    "status": "Submitted",
                    "conid": "12345",
                }
            ]
        }

    async def portfolio_positions(self, account_id: str) -> list[dict]:
        return [
            {
                "contractDesc": "AAPL",
                "conid": "12345",
                "position": 10,
                "mktValue": 1500.0,
            },
            {
                "contractDesc": "MSFT 15JAN27 400 C",
                "conid": "910001",
                "position": 1,
                "mktValue": 1250.0,
            },
        ]

    async def modify_order(self, **kwargs) -> list[dict]:
        return []

    async def cancel_order(self, **kwargs) -> dict:
        return {"cancelled": True}

    async def recent_trades(self) -> list[dict]:
        return []


@pytest.mark.asyncio
async def test_preview_order_reports_position_and_duplicate_context():
    svc = OrderService(
        order_adapter=FakeOrderAdapter(),
        market_data=FakeMarketDataAdapter(),
        account_adapter=FakeAccountAdapter(),
        account_id="DEMO",
    )

    result = await svc.preview(
        symbol="AAPL",
        side="BUY",
        quantity=20,
        order_type="LMT",
        price=155.0,
    )

    assert result["conid"] == "12345"
    assert result["estimated_notional_quote"] == 3100.0
    assert result["post_trade_position_shares"] == 35.0
    assert result["matching_live_orders"][0]["order_id"] == "LIVE-1"
    assert any("Matching live orders" in warning for warning in result["warnings"])


@pytest.mark.asyncio
async def test_preview_bracket_reports_risk_reward():
    svc = OrderService(
        order_adapter=FakeOrderAdapter(),
        market_data=FakeMarketDataAdapter(),
        account_adapter=FakeAccountAdapter(),
        account_id="DEMO",
    )

    result = await svc.preview_bracket(
        symbol="AAPL",
        side="BUY",
        quantity=10,
        entry_price=100.0,
        stop_price=95.0,
        target_price=115.0,
    )

    assert result["estimated_max_loss_quote"] == 50.0
    assert result["estimated_max_reward_quote"] == 150.0
    assert result["risk_reward_ratio"] == 3.0


@pytest.mark.asyncio
async def test_preview_option_order_uses_contract_multiplier():
    svc = OrderService(
        order_adapter=FakeOrderAdapter(),
        market_data=FakeMarketDataAdapter(),
        account_adapter=FakeAccountAdapter(),
        account_id="DEMO",
    )

    result = await svc.preview(
        symbol="MSFT",
        side="BUY",
        quantity=3,
        order_type="LMT",
        price=12.5,
        sec_type="OPT",
        expiry="2027-01-15",
        strike=400.0,
        right="C",
    )

    assert result["asset_class"] == "OPT"
    assert result["contract_multiplier"] == 100.0
    assert result["position_unit"] == "contracts"
    assert result["current_position_units"] == 1.0
    assert result["estimated_notional_quote"] == 3750.0


@pytest.mark.asyncio
async def test_submit_option_order_resolves_option_contract(db_session):
    fake_orders = FakeOrderAdapter()
    svc = OrderService(
        order_adapter=fake_orders,
        market_data=FakeMarketDataAdapter(),
        account_adapter=FakeAccountAdapter(),
        account_id="DEMO",
    )

    result = await svc.submit(
        session=db_session,
        symbol="MSFT",
        side="BUY",
        quantity=1,
        order_type="LMT",
        price=12.5,
        sec_type="OPT",
        expiry="2027-01-15",
        strike=400.0,
        right="C",
    )

    assert fake_orders.submit_order_calls == 1
    assert fake_orders.last_submit_order_kwargs["conid"] == 910001
    assert result["asset_class"] == "OPT"
    assert result["strike"] == 400.0
    assert result["right"] == "C"


@pytest.mark.asyncio
async def test_submit_order_passes_outside_rth_to_adapter_and_response(db_session):
    fake_orders = FakeOrderAdapter()
    svc = OrderService(
        order_adapter=fake_orders,
        market_data=FakeMarketDataAdapter(),
        account_adapter=FakeAccountAdapter(),
        account_id="DEMO",
    )

    result = await svc.submit(
        session=db_session,
        symbol="AAPL",
        side="BUY",
        quantity=2,
        order_type="LMT",
        price=101.5,
        outside_rth=True,
    )

    assert fake_orders.last_submit_order_kwargs["outside_rth"] is True
    assert result["outside_rth"] is True


@pytest.mark.asyncio
async def test_submit_bracket_passes_outside_rth_to_adapter_and_response(db_session):
    fake_orders = FakeOrderAdapter()
    svc = OrderService(
        order_adapter=fake_orders,
        market_data=FakeMarketDataAdapter(),
        account_adapter=FakeAccountAdapter(),
        account_id="DEMO",
    )

    result = await svc.submit_bracket(
        session=db_session,
        symbol="AAPL",
        side="BUY",
        quantity=2,
        entry_price=101.5,
        stop_price=96.0,
        target_price=115.0,
        outside_rth=True,
    )

    assert fake_orders.last_submit_bracket_kwargs["outside_rth"] is True
    assert result["outside_rth"] is True


@pytest.mark.asyncio
async def test_submit_order_is_idempotent_for_same_client_order_id(db_session):
    fake_orders = FakeOrderAdapter()
    svc = OrderService(
        order_adapter=fake_orders,
        market_data=FakeMarketDataAdapter(),
        account_adapter=FakeAccountAdapter(),
        account_id="DEMO",
    )

    first = await svc.submit(
        session=db_session,
        symbol="AAPL",
        side="BUY",
        quantity=2,
        order_type="LMT",
        price=101.5,
        client_order_id="idemp-1",
    )
    second = await svc.submit(
        session=db_session,
        symbol="AAPL",
        side="BUY",
        quantity=2,
        order_type="LMT",
        price=101.5,
        client_order_id="idemp-1",
    )

    assert fake_orders.submit_order_calls == 1
    assert second == first


@pytest.mark.asyncio
async def test_submit_order_rejects_reused_client_order_id_with_different_params(db_session):
    fake_orders = FakeOrderAdapter()
    svc = OrderService(
        order_adapter=fake_orders,
        market_data=FakeMarketDataAdapter(),
        account_adapter=FakeAccountAdapter(),
        account_id="DEMO",
    )

    await svc.submit(
        session=db_session,
        symbol="AAPL",
        side="BUY",
        quantity=2,
        order_type="LMT",
        price=101.5,
        client_order_id="idemp-2",
    )

    with pytest.raises(ValueError, match="different order"):
        await svc.submit(
            session=db_session,
            symbol="AAPL",
            side="BUY",
            quantity=3,
            order_type="LMT",
            price=101.5,
            client_order_id="idemp-2",
        )
