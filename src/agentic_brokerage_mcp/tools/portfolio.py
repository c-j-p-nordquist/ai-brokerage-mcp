from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

from agentic_brokerage_mcp.config import settings
from agentic_brokerage_mcp.db.engine import get_session
from agentic_brokerage_mcp.dependencies import (
    get_account_adapter,
    get_market_data_adapter,
    get_order_adapter,
)
from agentic_brokerage_mcp.services.order_service import OrderService
from agentic_brokerage_mcp.services.portfolio import PortfolioService
from agentic_brokerage_mcp.services.valuation import BASE_CURRENCY, safe_float


def _svc() -> PortfolioService:
    return PortfolioService(get_order_adapter(), get_account_adapter(), settings.ibkr_account_id)


def _order_svc() -> OrderService:
    return OrderService(
        get_order_adapter(),
        get_market_data_adapter(),
        get_account_adapter(),
        settings.ibkr_account_id,
    )


def register(mcp: FastMCP) -> None:

    @mcp.tool()
    async def portfolio(include_history: bool = True) -> dict:
        """Return positions, concentration, FX exposure, and optional order history."""
        svc = _svc()
        order_svc = _order_svc()

        if include_history:
            overview, live_orders, recent_trades = await asyncio.gather(
                svc.overview(),
                order_svc.live_orders(),
                order_svc.recent_trades(),
            )
        else:
            overview = await svc.overview()
            live_orders = None
            recent_trades = None

        positions = overview["positions"]
        summary = overview["summary"]

        nlv = safe_float(summary.get("net_liquidation"))
        cash = safe_float(summary.get("total_cash"))
        cash_pct = (cash / nlv * 100) if nlv else 0

        sorted_positions = sorted(
            positions,
            key=lambda p: abs(safe_float(p.get("allocation_pct"))),
            reverse=True,
        )

        concentration_warnings = [
            f"{p['symbol']} at {p['allocation_pct']}% exceeds 25% threshold"
            for p in sorted_positions
            if abs(safe_float(p.get("allocation_pct"))) > 25
        ]
        if cash_pct < 5:
            concentration_warnings.append(f"Cash at {cash_pct:.1f}% is below 5% minimum")

        currency_groups: dict[str, dict] = {}
        for p in sorted_positions:
            ccy = str(p.get("currency") or BASE_CURRENCY).upper()
            if ccy not in currency_groups:
                currency_groups[ccy] = {"market_value_base": 0.0, "symbols": []}
            currency_groups[ccy]["market_value_base"] += safe_float(p.get("market_value_base"))
            currency_groups[ccy]["symbols"].append(p["symbol"])
        currency_exposure = [
            {
                "currency": ccy,
                "market_value_base": round(v["market_value_base"], 2),
                "allocation_pct": round(v["market_value_base"] / nlv * 100, 2) if nlv else 0,
                "symbols": v["symbols"],
            }
            for ccy, v in sorted(
                currency_groups.items(), key=lambda x: -abs(x[1]["market_value_base"])
            )
        ]

        result: dict = {
            "account": {
                "net_liquidation": summary.get("net_liquidation"),
                "cash": summary.get("total_cash"),
                "cash_pct": round(cash_pct, 2),
                "buying_power": summary.get("buying_power"),
                "excess_liquidity": summary.get("excess_liquidity"),
                "base_currency": BASE_CURRENCY,
                "fx_rates": summary.get("fx_rates"),
            },
            "positions": sorted_positions,
            "concentration": {
                "top5_pct": round(
                    sum(safe_float(p.get("allocation_pct")) for p in sorted_positions[:5]), 2
                ),
                "warnings": concentration_warnings,
            },
            "currency_exposure": currency_exposure,
        }

        if include_history:
            async with get_session() as session:
                history_rows = await OrderService.order_history(session, limit=20)
            result["live_orders"] = live_orders
            result["recent_trades"] = recent_trades
            result["recent_order_history"] = [
                {
                    "id": str(r.id),
                    "created_at": r.created_at.isoformat(),
                    "ibkr_order_id": r.ibkr_order_id,
                    "symbol": r.symbol,
                    "side": r.side,
                    "order_type": r.order_type,
                    "quantity": float(r.quantity),
                    "price": float(r.price) if r.price is not None else None,
                    "stop_price": float(r.stop_price) if r.stop_price is not None else None,
                    "status": r.status,
                    "client_order_id": r.client_order_id,
                }
                for r in history_rows
            ]

        return result
