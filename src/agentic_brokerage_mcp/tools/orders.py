from __future__ import annotations

import time
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
from agentic_brokerage_mcp.services.audit import AuditService
from agentic_brokerage_mcp.services.order_service import OrderService


def _svc() -> OrderService:
    return OrderService(
        get_order_adapter(),
        get_market_data_adapter(),
        get_account_adapter(),
        settings.ibkr_account_id,
    )


def _require_mutation_allowed(action: str) -> None:
    if settings.broker_mode == "live" and not settings.enable_live_trading:
        raise PermissionError(
            f"{action} would touch a live brokerage account. Set "
            "AGENTIC_BROKERAGE_MCP_ENABLE_LIVE_TRADING=true to opt in."
        )


def register(mcp: FastMCP) -> None:

    @mcp.tool()
    async def submit_order(
        symbol: str,
        side: str,
        quantity: float,
        entry_price: float | None = None,
        stop_price: float | None = None,
        target_price: float | None = None,
        bracket: bool = True,
        order_type: str = "LMT",
        tif: str = "DAY",
        outside_rth: bool = False,
        dry_run: bool = True,
        agent_id: str | None = None,
        client_order_id: str | None = None,
        conid: str | None = None,
        sec_type: str = "STK",
        expiry: str | None = None,
        strike: float | None = None,
        right: str | None = None,
        exchange: str | None = None,
        underlying_conid: str | None = None,
    ) -> dict:
        """Preview or submit a stock or option order.

        Defaults to a dry-run bracket preview. Set bracket=False for a single leg.
        """
        svc = _svc()
        start = time.monotonic()

        if bracket:
            if dry_run:
                return await svc.preview_bracket(
                    symbol=symbol,
                    side=side,
                    quantity=quantity,
                    entry_price=entry_price,
                    stop_price=stop_price,
                    target_price=target_price,
                    tif=tif,
                    outside_rth=outside_rth,
                    conid=conid,
                    sec_type=sec_type,
                    expiry=expiry,
                    strike=strike,
                    right=right,
                    exchange=exchange,
                    underlying_conid=underlying_conid,
                )
            _require_mutation_allowed("submit_order")
            async with get_session() as session:
                result = await svc.submit_bracket(
                    session=session,
                    symbol=symbol,
                    side=side,
                    quantity=quantity,
                    entry_price=entry_price,
                    stop_price=stop_price,
                    target_price=target_price,
                    tif=tif,
                    outside_rth=outside_rth,
                    agent_id=agent_id,
                    conid=conid,
                    client_order_id=client_order_id,
                    sec_type=sec_type,
                    expiry=expiry,
                    strike=strike,
                    right=right,
                    exchange=exchange,
                    underlying_conid=underlying_conid,
                )
                await AuditService(session).log(
                    action="order.submit_bracket",
                    resource="orders",
                    resource_id=result.get("parent_order_id"),
                    parameters={
                        "symbol": symbol,
                        "side": side,
                        "quantity": quantity,
                        "entry_price": entry_price,
                        "stop_price": stop_price,
                        "target_price": target_price,
                        "tif": tif,
                        "outside_rth": outside_rth,
                        "conid": conid,
                        "client_order_id": client_order_id,
                        "sec_type": sec_type,
                    },
                    result_summary={"status": result.get("status")},
                    agent_id=agent_id,
                    duration_ms=int((time.monotonic() - start) * 1000),
                )
            return result

        # Non-bracket path: validate STP_LMT parameters.
        if order_type == "STP_LMT":
            if entry_price is None:
                raise ValueError("STP_LMT orders require a limit price (entry_price=)")
            if stop_price is None:
                raise ValueError("STP_LMT orders require a stop trigger price (stop_price=)")
            if side.upper() == "SELL" and stop_price < entry_price:
                raise ValueError(
                    f"STP_LMT SELL: stop_price ({stop_price}) must be above limit price "
                    f"({entry_price}). The stop triggers first, then places a limit "
                    "order at entry_price."
                )
            if side.upper() == "BUY" and stop_price > entry_price:
                raise ValueError(
                    f"STP_LMT BUY: stop_price ({stop_price}) must be below limit price "
                    f"({entry_price}). The stop triggers first, then places a limit "
                    "order at entry_price."
                )

        if dry_run:
            return await svc.preview(
                symbol=symbol,
                side=side,
                quantity=quantity,
                order_type=order_type,
                price=entry_price,
                stop_price=stop_price,
                tif=tif,
                outside_rth=outside_rth,
                conid=conid,
                sec_type=sec_type,
                expiry=expiry,
                strike=strike,
                right=right,
                exchange=exchange,
                underlying_conid=underlying_conid,
            )
        _require_mutation_allowed("submit_order")
        async with get_session() as session:
            result = await svc.submit(
                session=session,
                symbol=symbol,
                side=side,
                quantity=quantity,
                order_type=order_type,
                price=entry_price,
                stop_price=stop_price,
                tif=tif,
                outside_rth=outside_rth,
                agent_id=agent_id,
                conid=conid,
                client_order_id=client_order_id,
                sec_type=sec_type,
                expiry=expiry,
                strike=strike,
                right=right,
                exchange=exchange,
                underlying_conid=underlying_conid,
            )
            await AuditService(session).log(
                action="order.submit",
                resource="orders",
                resource_id=result.get("order_id"),
                parameters={
                    "symbol": symbol,
                    "side": side,
                    "quantity": quantity,
                    "order_type": order_type,
                    "price": entry_price,
                    "stop_price": stop_price,
                    "tif": tif,
                    "outside_rth": outside_rth,
                    "conid": conid,
                    "client_order_id": client_order_id,
                    "sec_type": sec_type,
                },
                result_summary={"status": result.get("status")},
                agent_id=agent_id,
                duration_ms=int((time.monotonic() - start) * 1000),
            )
        return result

    @mcp.tool()
    async def manage_order(
        action: str,
        order_id: str | None = None,
        price: float | None = None,
        quantity: float | None = None,
        order_type: str | None = None,
        tif: str | None = None,
        outside_rth: bool | None = None,
        agent_id: str | None = None,
    ) -> dict | list:
        """List, cancel, or modify live orders."""
        svc = _svc()

        if action == "list":
            return await svc.live_orders()

        if action == "cancel":
            _require_mutation_allowed("manage_order.cancel")
            if not order_id:
                raise ValueError("order_id is required for action='cancel'")
            start = time.monotonic()
            result = await svc.cancel(order_id=order_id)
            async with get_session() as session:
                await AuditService(session).log(
                    action="order.cancel",
                    resource="orders",
                    resource_id=order_id,
                    parameters={"order_id": order_id},
                    result_summary=result,
                    agent_id=agent_id,
                    duration_ms=int((time.monotonic() - start) * 1000),
                )
            return result

        if action == "modify":
            _require_mutation_allowed("manage_order.modify")
            if not order_id:
                raise ValueError("order_id is required for action='modify'")
            modifications = {
                k: v
                for k, v in {
                    "price": price,
                    "quantity": quantity,
                    "orderType": order_type,
                    "tif": tif,
                    "outsideRTH": outside_rth,
                }.items()
                if v is not None
            }
            result = await svc.modify(order_id=order_id, modifications=modifications)
            async with get_session() as session:
                await AuditService(session).log(
                    action="order.modify",
                    resource="orders",
                    resource_id=order_id,
                    parameters={"order_id": order_id, **modifications},
                    result_summary={"count": len(result)},
                    agent_id=agent_id,
                )
            return result

        raise ValueError(f"Unknown action {action!r}. Use 'list', 'cancel', or 'modify'.")
