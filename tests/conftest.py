from __future__ import annotations

import os

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from agentic_brokerage_mcp.db.models import Base

os.environ.setdefault("AGENTIC_BROKERAGE_MCP_IBKR_BASE_URL", "https://localhost:5001/v1/api")
os.environ.setdefault("AGENTIC_BROKERAGE_MCP_IBKR_ACCOUNT_ID", "DEMO")
os.environ.setdefault("AGENTIC_BROKERAGE_MCP_BROKER_MODE", "demo")


@pytest_asyncio.fixture
async def db_session() -> AsyncSession:
    """Fresh in-memory SQLite database for each test."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()
