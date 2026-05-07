from __future__ import annotations

import pytest

from agentic_brokerage_mcp.services.audit import AuditService


@pytest.mark.asyncio
async def test_audit_log_create_and_query(db_session):
    svc = AuditService(db_session)
    entry = await svc.log(
        action="order.submit",
        resource="orders",
        resource_id="ORD-123",
        parameters={"symbol": "AAPL", "side": "BUY"},
        result_summary={"status": "ok"},
        agent_id="agent-test",
        duration_ms=42,
    )
    assert entry.id is not None
    assert entry.action == "order.submit"

    results = await svc.query(action="order.submit")
    assert len(results) >= 1
    assert any(r.resource_id == "ORD-123" for r in results)


@pytest.mark.asyncio
async def test_audit_query_by_agent(db_session):
    svc = AuditService(db_session)
    await svc.log(action="a", resource="r", agent_id="agent-1")
    await svc.log(action="b", resource="r", agent_id="agent-2")

    results = await svc.query(agent_id="agent-1")
    assert len(results) >= 1
    assert all(r.agent_id == "agent-1" for r in results)


@pytest.mark.asyncio
async def test_audit_stats(db_session):
    svc = AuditService(db_session)
    for _ in range(5):
        await svc.log(action="order.submit", resource="orders")
    for _ in range(3):
        await svc.log(action="watchlist.add", resource="watchlist")

    stats = await svc.stats(days=1)
    assert stats["total_actions"] >= 8
    assert stats["actions_by_type"].get("order.submit", 0) >= 5
