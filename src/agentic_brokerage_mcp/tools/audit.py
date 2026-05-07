from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

from agentic_brokerage_mcp.db.engine import get_session
from agentic_brokerage_mcp.services.audit import AuditService


def _parse_duration(s: str) -> datetime:
    s = s.strip()
    unit = s[-1].lower()
    try:
        value = int(s[:-1])
    except ValueError as exc:
        raise ValueError(f"Invalid duration: {s!r}. Use e.g. '7d', '24h', '30m'.") from exc
    delta = {
        "d": timedelta(days=value),
        "h": timedelta(hours=value),
        "m": timedelta(minutes=value),
    }.get(unit)
    if delta is None:
        raise ValueError(f"Unknown duration unit '{unit}'. Use 'd', 'h', or 'm'.")
    return datetime.now(UTC) - delta


def register(mcp: FastMCP) -> None:

    @mcp.tool()
    async def audit(
        action: str | None = None,
        resource: str | None = None,
        last: str | None = None,
        limit: int = 50,
    ) -> dict:
        """Query recent audit entries and 7-day action statistics."""
        since = _parse_duration(last) if last else None
        async with get_session() as session:
            svc = AuditService(session)
            entries = await svc.query(
                action=action,
                resource=resource,
                since=since,
                limit=min(limit, 500),
            )
            stats = await svc.stats(days=7)
        return {
            "entries": [
                {
                    "id": str(e.id),
                    "created_at": e.created_at.isoformat(),
                    "action": e.action,
                    "resource": e.resource,
                    "resource_id": e.resource_id,
                    "parameters": e.parameters,
                    "result_summary": e.result_summary,
                    "agent_id": e.agent_id,
                    "duration_ms": e.duration_ms,
                }
                for e in entries
            ],
            "stats_7d": stats,
        }
