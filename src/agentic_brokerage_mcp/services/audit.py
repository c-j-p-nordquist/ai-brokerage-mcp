from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from agentic_brokerage_mcp.db.models import AuditLog

logger = logging.getLogger("agentic_brokerage_mcp.services.audit")


class AuditService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def log(
        self,
        *,
        action: str,
        resource: str,
        resource_id: str | None = None,
        parameters: dict[str, Any] | None = None,
        result_summary: dict[str, Any] | None = None,
        agent_id: str | None = None,
        duration_ms: int | None = None,
    ) -> AuditLog:
        entry = AuditLog(
            id=uuid.uuid4(),
            created_at=datetime.now(UTC),
            action=action,
            resource=resource,
            resource_id=resource_id,
            parameters=parameters,
            result_summary=result_summary,
            agent_id=agent_id,
            duration_ms=duration_ms,
        )
        self.session.add(entry)
        await self.session.commit()
        return entry

    async def query(
        self,
        *,
        action: str | None = None,
        resource: str | None = None,
        agent_id: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[AuditLog]:
        stmt = select(AuditLog).order_by(AuditLog.created_at.desc())
        if action:
            stmt = stmt.where(AuditLog.action == action)
        if resource:
            stmt = stmt.where(AuditLog.resource == resource)
        if agent_id:
            stmt = stmt.where(AuditLog.agent_id == agent_id)
        if since:
            stmt = stmt.where(AuditLog.created_at >= since)
        if until:
            stmt = stmt.where(AuditLog.created_at <= until)
        stmt = stmt.offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def stats(self, days: int = 7) -> dict[str, Any]:
        since = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        from datetime import timedelta

        since = since - timedelta(days=days)

        count_stmt = select(func.count(AuditLog.id)).where(AuditLog.created_at >= since)
        total = (await self.session.execute(count_stmt)).scalar() or 0

        action_stmt = (
            select(AuditLog.action, func.count(AuditLog.id).label("cnt"))
            .where(AuditLog.created_at >= since)
            .group_by(AuditLog.action)
            .order_by(func.count(AuditLog.id).desc())
            .limit(20)
        )
        action_rows = (await self.session.execute(action_stmt)).all()

        return {
            "period_days": days,
            "total_actions": total,
            "actions_by_type": {row[0]: row[1] for row in action_rows},
        }
