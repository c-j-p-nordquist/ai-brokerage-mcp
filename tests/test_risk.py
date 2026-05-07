from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from agentic_brokerage_mcp.ibkr.market_data import BarData, IBKRContract
from agentic_brokerage_mcp.services.risk import RiskService


class FakeMarketData:
    async def resolve_contract(
        self,
        symbol: str,
        sec_type: str = "STK",
        *,
        conid: str | None = None,
    ) -> IBKRContract:
        return IBKRContract(
            conid=conid or "12345",
            symbol=symbol,
            exchange="SMART",
            asset_class="STK",
        )

    async def get_historical_bars(
        self, *, conid: str, period: str = "3M", bar: str = "1d", outside_rth: bool = False
    ) -> list[BarData]:
        bars = []
        now = datetime.now(UTC)
        for i in range(60):
            price = 150.0 + math.sin(i / 5) * 5
            bars.append(
                BarData(
                    timestamp=now - timedelta(days=60 - i),
                    open=price - 0.3,
                    high=price + 1.5,
                    low=price - 1.5,
                    close=price,
                    volume=500000,
                )
            )
        return bars

    async def get_quotes(self, conids: list[str]) -> list[dict[str, Any]]:
        return [{"conid": conids[0], "31": 155.0}]


class FakeAccountAdapter:
    async def account_summary(self, account_id: str) -> dict[str, Any]:
        return {
            "net_liquidation": 100000.0,
            "total_cash": 30000.0,
            "available_funds": 25000.0,
            "buying_power": 200000.0,
            "gross_position_value": 70000.0,
            "initial_margin": 35000.0,
            "maintenance_margin": 25000.0,
            "excess_liquidity": 30000.0,
        }


class FakeOrderAdapter:
    def __init__(self, *, live_orders_payload: dict[str, Any] | None = None):
        self.live_orders_payload = live_orders_payload or {"orders": []}

    async def portfolio_positions(self, account_id: str) -> list[dict[str, Any]]:
        return [
            {
                "contractDesc": "AAPL",
                "conid": "12345",
                "mktValue": 30000,
                "position": 100,
                "mktPrice": 150.0,
            },
            {
                "contractDesc": "MSFT",
                "conid": "23456",
                "mktValue": 25000,
                "position": 60,
                "mktPrice": 400.0,
            },
            {
                "contractDesc": "GOOGL",
                "conid": "34567",
                "mktValue": 15000,
                "position": 10,
                "mktPrice": 170.0,
            },
        ]

    async def live_orders(self) -> dict[str, Any]:
        return self.live_orders_payload


@pytest.fixture
def risk_service():
    return RiskService(
        market_data=FakeMarketData(),
        account_adapter=FakeAccountAdapter(),
        order_adapter=FakeOrderAdapter(),
        account_id="DEMO",
    )


@pytest.mark.asyncio
async def test_position_size_with_stop_distance(risk_service):
    result = await risk_service.position_size("AAPL", risk_pct=1.0, stop_distance=5.0)
    assert result["symbol"] == "AAPL"
    assert result["account_value"] == 100000.0
    assert result["risk_amount"] == 1000.0
    assert result["suggested_shares"] == 200  # 1000 / 5.0
    assert result["stop_distance"] == 5.0


@pytest.mark.asyncio
async def test_position_size_auto_stop(risk_service):
    result = await risk_service.position_size("AAPL", risk_pct=2.0)
    assert result["symbol"] == "AAPL"
    assert result["risk_amount"] == 2000.0
    assert result["stop_distance"] is not None
    assert result["suggested_shares"] > 0
    assert result["last_price"] > 0
    assert result["estimated_cost"] > 0


class EmptyDailyHistoryFakeMarketData(FakeMarketData):
    async def get_historical_bars(
        self, *, conid: str, period: str = "3M", bar: str = "1d", outside_rth: bool = False
    ) -> list[BarData]:
        if period == "1M" and bar == "1d":
            return await super().get_historical_bars(
                conid=conid, period=period, bar=bar, outside_rth=outside_rth
            )
        return []


@pytest.mark.asyncio
async def test_position_size_uses_bars_for_price_when_short_history_is_empty():
    svc = RiskService(
        market_data=EmptyDailyHistoryFakeMarketData(),
        account_adapter=FakeAccountAdapter(),
        order_adapter=FakeOrderAdapter(),
        account_id="DEMO",
    )

    result = await svc.position_size("AAPL", risk_pct=1.0)

    assert result["suggested_shares"] > 0
    assert result["last_price"] > 0
    assert result["estimated_cost"] > 0


@pytest.mark.asyncio
async def test_portfolio_aware_position_size_reports_baseline_context(risk_service):
    result = await risk_service.portfolio_aware_position_size(
        "AAPL",
        risk_pct=1.0,
        stop_distance=5.0,
    )

    assert result["baseline_shares"] == 200
    assert result["current_position_shares"] == 100.0
    assert result["current_position_pct"] > 0
    assert result["post_trade_position_pct"] > result["current_position_pct"]
    assert result["estimated_initial_margin_used"] > 0
    assert any("exposure" in note for note in result["observations"])


class NegativeCashButHealthyMarginAccountAdapter(FakeAccountAdapter):
    async def account_summary(self, account_id: str) -> dict[str, Any]:
        summary = await super().account_summary(account_id)
        summary["total_cash"] = -5000.0
        return summary


@pytest.mark.asyncio
async def test_portfolio_aware_position_size_keeps_baseline_even_with_negative_cash():
    svc = RiskService(
        market_data=FakeMarketData(),
        account_adapter=NegativeCashButHealthyMarginAccountAdapter(),
        order_adapter=FakeOrderAdapter(),
        account_id="DEMO",
    )

    result = await svc.portfolio_aware_position_size(
        "NVDA",
        risk_pct=1.0,
        stop_distance=5.0,
    )

    assert result["baseline_shares"] == 200
    assert result["post_trade_cash_base"] < 0
    assert result["post_trade_available_funds"] > 0
    assert result["post_trade_excess_liquidity"] > 0
    assert any("rely on margin" in note for note in result["observations"])


@pytest.mark.asyncio
async def test_portfolio_aware_position_size_reports_margin_context():
    svc = RiskService(
        market_data=FakeMarketData(),
        account_adapter=NegativeCashButHealthyMarginAccountAdapter(),
        order_adapter=FakeOrderAdapter(),
        account_id="DEMO",
    )

    result = await svc.portfolio_aware_position_size(
        "NVDA",
        risk_pct=1.0,
        stop_distance=5.0,
    )

    assert result["margin_ratio_source"] == "portfolio_implied"
    assert result["estimated_initial_margin_ratio"] == 0.5
    assert result["estimated_maintenance_margin_ratio"] == round(25000.0 / 70000.0, 4)


class LowMarginHeadroomAccountAdapter(FakeAccountAdapter):
    async def account_summary(self, account_id: str) -> dict[str, Any]:
        summary = await super().account_summary(account_id)
        summary["available_funds"] = 2000.0
        summary["excess_liquidity"] = 2500.0
        return summary


@pytest.mark.asyncio
async def test_portfolio_aware_position_size_reports_margin_shortfall_as_observation():
    svc = RiskService(
        market_data=FakeMarketData(),
        account_adapter=LowMarginHeadroomAccountAdapter(),
        order_adapter=FakeOrderAdapter(),
        account_id="DEMO",
    )

    result = await svc.portfolio_aware_position_size(
        "NVDA",
        risk_pct=1.0,
        stop_distance=5.0,
    )

    assert result["baseline_shares"] == 200
    assert result["post_trade_available_funds"] < 0
    assert result["post_trade_excess_liquidity"] < 0
    assert any("available funds" in note for note in result["observations"])
    assert any("excess liquidity" in note for note in result["observations"])


@pytest.mark.asyncio
async def test_portfolio_aware_position_size_reports_pending_orders_context():
    svc = RiskService(
        market_data=FakeMarketData(),
        account_adapter=FakeAccountAdapter(),
        order_adapter=FakeOrderAdapter(
            live_orders_payload={
                "orders": [
                    {
                        "ticker": "GOOGL",
                        "side": "BUY",
                        "remainingQuantity": 5,
                        "status": "Submitted",
                    },
                ]
            }
        ),
        account_id="DEMO",
    )

    result = await svc.portfolio_aware_position_size(
        "GOOGL",
        risk_pct=1.0,
        stop_distance=5.0,
    )

    assert result["pending_buy_shares"] == 5
    assert result["effective_current_shares"] == 15
    assert result["baseline_shares"] == 200
    assert any(
        "Live orders already affect GOOGL exposure" in note for note in result["observations"]
    )


@pytest.mark.asyncio
async def test_portfolio_aware_position_size_estimates_added_open_risk(risk_service):
    result = await risk_service.portfolio_aware_position_size(
        "NVDA",
        risk_pct=1.0,
        stop_distance=5.0,
    )

    assert result["baseline_shares"] == 200
    assert result["estimated_open_risk_added_base"] == 1000.0


@pytest.mark.asyncio
async def test_stop_loss_levels(risk_service):
    result = await risk_service.stop_loss_levels("AAPL")
    assert result["symbol"] == "AAPL"
    assert result["atr_14"] > 0
    assert "tight" in result["levels"]
    assert "moderate" in result["levels"]
    assert "wide" in result["levels"]
    assert result["levels"]["tight"]["stop_price"] > result["levels"]["wide"]["stop_price"]


@pytest.mark.asyncio
async def test_concentration(risk_service):
    result = await risk_service.concentration()
    assert result["account_value"] == 100000.0
    assert result["cash"] == 30000.0
    assert len(result["holdings"]) == 3
    total_pct = sum(h["allocation_pct"] for h in result["holdings"])
    assert 60 < total_pct < 80


@pytest.mark.asyncio
async def test_rebalance(risk_service):
    result = await risk_service.rebalance({"AAPL": 40, "MSFT": 30, "CASH": 30})
    assert result["account_value"] == 100000.0
    assert isinstance(result["trades_needed"], list)
