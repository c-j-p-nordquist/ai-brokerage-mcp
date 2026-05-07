from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

from agentic_brokerage_mcp.config import settings
from agentic_brokerage_mcp.dependencies import (
    get_account_adapter,
    get_market_data_adapter,
    get_order_adapter,
)
from agentic_brokerage_mcp.services.risk import RiskService


def _svc() -> RiskService:
    return RiskService(
        get_market_data_adapter(),
        get_account_adapter(),
        get_order_adapter(),
        settings.ibkr_account_id,
    )


def register(mcp: FastMCP) -> None:

    @mcp.tool()
    async def position_size(
        symbol: str,
        risk_pct: float = 1.0,
        stop_distance: float | None = None,
        conid: str | None = None,
    ) -> dict:
        """Return baseline risk-based sizing from account value and stop distance."""
        return await _svc().position_size(
            symbol,
            risk_pct=risk_pct,
            stop_distance=stop_distance,
            conid=conid,
        )
