from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from agentic_brokerage_mcp.config import settings
from agentic_brokerage_mcp.db.models import Base

_engine = None
_session_factory = None
_initialized = False


def _get_engine():
    global _engine
    if _engine is None:
        path = Path(settings.db_path).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        _engine = create_async_engine(f"sqlite+aiosqlite:///{path}", echo=False)
    return _engine


def _get_factory():
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(_get_engine(), expire_on_commit=False)
    return _session_factory


async def init_db() -> None:
    """Create all tables if they do not yet exist. Idempotent."""
    global _initialized
    if _initialized:
        return
    async with _get_engine().begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _upgrade_sqlite_schema(conn)
    _initialized = True


@asynccontextmanager
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    await init_db()
    async with _get_factory()() as session:
        yield session


async def _upgrade_sqlite_schema(conn) -> None:
    table_info = await conn.exec_driver_sql("PRAGMA table_info(order_history)")
    columns = {row[1] for row in table_info.fetchall()}

    additions = {
        "conid": "ALTER TABLE order_history ADD COLUMN conid VARCHAR(32)",
        "stop_price": "ALTER TABLE order_history ADD COLUMN stop_price NUMERIC(16, 4)",
        "client_order_id": "ALTER TABLE order_history ADD COLUMN client_order_id VARCHAR(128)",
    }
    for column_name, ddl in additions.items():
        if column_name not in columns:
            await conn.execute(text(ddl))

    await conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_order_history_client_order_id "
            "ON order_history (client_order_id)"
        )
    )

    # watchlist_items migrations
    wl_info = await conn.exec_driver_sql("PRAGMA table_info(watchlist_items)")
    wl_columns = {row[1] for row in wl_info.fetchall()}

    if "target_weight" not in wl_columns:
        await conn.execute(
            text("ALTER TABLE watchlist_items ADD COLUMN target_weight NUMERIC(5, 4)")
        )
