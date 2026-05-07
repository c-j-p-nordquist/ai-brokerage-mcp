from __future__ import annotations

import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

from agentic_brokerage_mcp.db.engine import get_session
from agentic_brokerage_mcp.services.audit import AuditService
from agentic_brokerage_mcp.services.watchlist import WatchlistService


def _item_dict(item) -> dict:
    return {
        "id": str(item.id),
        "symbol": item.symbol,
        "added_at": item.added_at.isoformat(),
        "updated_at": item.updated_at.isoformat(),
        "status": item.status,
        "notes": item.notes,
        "tags": item.tags,
        "target_buy_price": float(item.target_buy_price)
        if item.target_buy_price is not None
        else None,
        "target_sell_price": float(item.target_sell_price)
        if item.target_sell_price is not None
        else None,
        "stop_loss_price": float(item.stop_loss_price)
        if item.stop_loss_price is not None
        else None,
        "target_weight": float(item.target_weight) if item.target_weight is not None else None,
        "rationale": item.rationale,
        "last_reviewed_at": item.last_reviewed_at.isoformat() if item.last_reviewed_at else None,
        "conid": item.conid,
    }


def register(mcp: FastMCP) -> None:

    @mcp.tool()
    async def manage_watchlist(
        action: str,
        symbol: str | None = None,
        status: str | None = None,
        notes: str | None = None,
        rationale: str | None = None,
        tags: list[str] | None = None,
        target_buy_price: float | None = None,
        target_sell_price: float | None = None,
        stop_loss_price: float | None = None,
        target_weight: float | None = None,
        conid: str | None = None,
        tag: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list | dict:
        """List or mutate watchlist items."""
        if action == "list":
            async with get_session() as session:
                items = await WatchlistService(session).list(
                    status=status, tag=tag, limit=limit, offset=offset
                )
            return [_item_dict(i) for i in items]

        if not symbol:
            raise ValueError(f"symbol is required for action='{action}'")

        if action == "add":
            start = time.monotonic()
            async with get_session() as session:
                item = await WatchlistService(session).add(
                    symbol=symbol,
                    notes=notes,
                    rationale=rationale,
                    tags=tags,
                    target_buy_price=target_buy_price,
                    target_sell_price=target_sell_price,
                    stop_loss_price=stop_loss_price,
                    target_weight=target_weight,
                    status=status or "watching",
                    conid=conid,
                )
                await AuditService(session).log(
                    action="watchlist.add",
                    resource="watchlist",
                    resource_id=symbol.upper(),
                    parameters={"symbol": symbol, "status": status or "watching"},
                    result_summary={"id": str(item.id)},
                    duration_ms=int((time.monotonic() - start) * 1000),
                )
            return _item_dict(item)

        if action == "update":
            async with get_session() as session:
                item = await WatchlistService(session).update(
                    symbol,
                    status=status,
                    notes=notes,
                    rationale=rationale,
                    tags=tags,
                    target_buy_price=target_buy_price,
                    target_sell_price=target_sell_price,
                    stop_loss_price=stop_loss_price,
                    target_weight=target_weight,
                    conid=conid,
                )
            if item is None:
                raise ValueError(f"Symbol '{symbol}' not found on watchlist")
            return _item_dict(item)

        if action == "remove":
            async with get_session() as session:
                removed = await WatchlistService(session).remove(symbol)
                if removed:
                    await AuditService(session).log(
                        action="watchlist.remove",
                        resource="watchlist",
                        resource_id=symbol.upper(),
                    )
            if not removed:
                raise ValueError(f"Symbol '{symbol}' not found on watchlist")
            return {"removed": True, "symbol": symbol.upper()}

        if action == "review":
            async with get_session() as session:
                item = await WatchlistService(session).review(symbol, notes=notes)
            if item is None:
                raise ValueError(f"Symbol '{symbol}' not found on watchlist")
            return _item_dict(item)

        raise ValueError(
            f"Unknown action {action!r}. Use 'list', 'add', 'update', 'remove', or 'review'."
        )
