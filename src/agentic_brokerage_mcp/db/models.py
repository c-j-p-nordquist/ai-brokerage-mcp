from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import JSON, DateTime, Numeric, String, Text, Uuid
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    action: Mapped[str] = mapped_column(String(128), index=True)
    resource: Mapped[str] = mapped_column(String(64), index=True)
    resource_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    parameters: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    result_summary: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    agent_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    duration_ms: Mapped[int | None] = mapped_column(nullable=True)


class WatchlistItem(Base):
    __tablename__ = "watchlist_items"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    symbol: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )
    status: Mapped[str] = mapped_column(String(32), default="watching")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    tags: Mapped[list | None] = mapped_column(JSON, nullable=True)
    target_buy_price: Mapped[float | None] = mapped_column(Numeric(16, 4), nullable=True)
    target_sell_price: Mapped[float | None] = mapped_column(Numeric(16, 4), nullable=True)
    stop_loss_price: Mapped[float | None] = mapped_column(Numeric(16, 4), nullable=True)
    target_weight: Mapped[float | None] = mapped_column(Numeric(5, 4), nullable=True)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    conid: Mapped[str | None] = mapped_column(String(32), nullable=True)


class OrderHistory(Base):
    __tablename__ = "order_history"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    ibkr_order_id: Mapped[str] = mapped_column(String(64), index=True)
    conid: Mapped[str | None] = mapped_column(String(32), nullable=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    side: Mapped[str] = mapped_column(String(8))
    order_type: Mapped[str] = mapped_column(String(16))
    quantity: Mapped[float] = mapped_column(Numeric(16, 4))
    price: Mapped[float | None] = mapped_column(Numeric(16, 4), nullable=True)
    stop_price: Mapped[float | None] = mapped_column(Numeric(16, 4), nullable=True)
    status: Mapped[str] = mapped_column(String(32))
    client_order_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    raw_response: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    agent_id: Mapped[str | None] = mapped_column(String(128), nullable=True)


class PortfolioSnapshot(Base):
    __tablename__ = "portfolio_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    total_value: Mapped[float] = mapped_column(Numeric(16, 2))
    cash: Mapped[float] = mapped_column(Numeric(16, 2))
    positions: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    allocation: Mapped[dict | None] = mapped_column(JSON, nullable=True)
