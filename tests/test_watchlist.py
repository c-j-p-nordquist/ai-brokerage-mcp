from __future__ import annotations

import pytest

from agentic_brokerage_mcp.services.watchlist import WatchlistService


@pytest.mark.asyncio
async def test_watchlist_crud(db_session):
    svc = WatchlistService(db_session)

    item = await svc.add(symbol="AAPL", notes="Strong Q4 earnings", status="watching")
    assert item.symbol == "AAPL"
    assert item.status == "watching"

    fetched = await svc.get("AAPL")
    assert fetched is not None
    assert fetched.notes == "Strong Q4 earnings"

    updated = await svc.update("AAPL", status="ready", target_buy_price=150.0)
    assert updated is not None
    assert updated.status == "ready"
    assert float(updated.target_buy_price) == 150.0

    items = await svc.list()
    assert len(items) == 1

    removed = await svc.remove("AAPL")
    assert removed is True

    items = await svc.list()
    assert len(items) == 0


@pytest.mark.asyncio
async def test_watchlist_review(db_session):
    svc = WatchlistService(db_session)
    await svc.add(symbol="MSFT", notes="Initial note")

    reviewed = await svc.review("MSFT", notes="Still bullish after review")
    assert reviewed is not None
    assert reviewed.last_reviewed_at is not None
    assert "Still bullish" in reviewed.notes


@pytest.mark.asyncio
async def test_watchlist_filter_by_status(db_session):
    svc = WatchlistService(db_session)
    await svc.add(symbol="A", status="watching")
    await svc.add(symbol="B", status="ready")
    await svc.add(symbol="C", status="watching")

    watching = await svc.list(status="watching")
    assert len(watching) == 2

    ready = await svc.list(status="ready")
    assert len(ready) == 1
    assert ready[0].symbol == "B"


@pytest.mark.asyncio
async def test_watchlist_not_found(db_session):
    svc = WatchlistService(db_session)
    assert await svc.get("NOPE") is None
    assert await svc.update("NOPE", status="x") is None
    assert await svc.remove("NOPE") is False
