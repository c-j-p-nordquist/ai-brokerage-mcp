from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agentic_brokerage_mcp.db.models import WatchlistItem


class WatchlistService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def list(
        self,
        *,
        status: str | None = None,
        tag: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[WatchlistItem]:
        stmt = select(WatchlistItem).order_by(WatchlistItem.added_at.desc())
        if status:
            stmt = stmt.where(WatchlistItem.status == status)
        stmt = stmt.offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        items = list(result.scalars().all())
        if tag:
            items = [item for item in items if item.tags and tag in item.tags]
        return items

    async def get(self, symbol: str) -> WatchlistItem | None:
        stmt = select(WatchlistItem).where(WatchlistItem.symbol == symbol.upper())
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def add(
        self,
        *,
        symbol: str,
        notes: str | None = None,
        rationale: str | None = None,
        tags: list[str] | None = None,
        target_buy_price: float | None = None,
        target_sell_price: float | None = None,
        stop_loss_price: float | None = None,
        target_weight: float | None = None,
        status: str = "watching",
        conid: str | None = None,
    ) -> WatchlistItem:
        item = WatchlistItem(
            id=uuid.uuid4(),
            symbol=symbol.upper(),
            added_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
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
        self.session.add(item)
        await self.session.commit()
        await self.session.refresh(item)
        return item

    async def update(self, symbol: str, **fields: Any) -> WatchlistItem | None:
        item = await self.get(symbol)
        if not item:
            return None

        allowed = {
            "status",
            "notes",
            "rationale",
            "tags",
            "target_buy_price",
            "target_sell_price",
            "stop_loss_price",
            "target_weight",
            "conid",
        }
        for key, value in fields.items():
            if key in allowed and value is not None:
                setattr(item, key, value)
        item.updated_at = datetime.now(UTC)
        await self.session.commit()
        await self.session.refresh(item)
        return item

    async def remove(self, symbol: str) -> bool:
        item = await self.get(symbol)
        if not item:
            return False
        await self.session.delete(item)
        await self.session.commit()
        return True

    async def review(self, symbol: str, notes: str | None = None) -> WatchlistItem | None:
        item = await self.get(symbol)
        if not item:
            return None
        item.last_reviewed_at = datetime.now(UTC)
        if notes:
            existing = item.notes or ""
            timestamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M")
            item.notes = f"{existing}\n\n[{timestamp}] {notes}".strip()
        item.updated_at = datetime.now(UTC)
        await self.session.commit()
        await self.session.refresh(item)
        return item
