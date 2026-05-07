from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agentic_brokerage_mcp.db.models import PortfolioSnapshot
from agentic_brokerage_mcp.ibkr.account import IBKRAccountAdapter
from agentic_brokerage_mcp.ibkr.orders import IBKROrderAdapter
from agentic_brokerage_mcp.services.valuation import (
    BASE_CURRENCY,
    convert_native_to_base,
    estimate_currency_rates,
    safe_float,
    summarize_fx_sources,
)


class PortfolioService:
    def __init__(
        self,
        order_adapter: IBKROrderAdapter,
        account_adapter: IBKRAccountAdapter,
        account_id: str,
    ):
        self.order_adapter = order_adapter
        self.account_adapter = account_adapter
        self.account_id = account_id

    async def positions(self) -> list[dict[str, Any]]:
        raw_positions, account, ledger = await self._fetch_portfolio_inputs()
        return self._build_positions(raw_positions, account, ledger)

    async def summary(self) -> dict[str, Any]:
        raw_positions, account, ledger = await self._fetch_portfolio_inputs()
        positions = self._build_positions(raw_positions, account, ledger)
        return self._build_summary(account, ledger, positions)

    async def overview(self) -> dict[str, Any]:
        raw_positions, account, ledger = await self._fetch_portfolio_inputs()
        positions = self._build_positions(raw_positions, account, ledger)
        return {
            "positions": positions,
            "summary": self._build_summary(account, ledger, positions),
        }

    async def capture_snapshot(self, session: AsyncSession) -> PortfolioSnapshot:
        raw_positions, account, ledger = await self._fetch_portfolio_inputs()
        positions = self._build_positions(raw_positions, account, ledger)

        total_value = float(account.get("net_liquidation", 0) or 0)
        cash = float(account.get("total_cash", 0) or 0)
        allocation = {
            p["symbol"]: {
                "allocation_pct": p["allocation_pct"],
                "market_value_base": p.get("market_value_base"),
                "currency": p.get("currency"),
            }
            for p in positions
            if p.get("symbol")
        }

        snapshot = PortfolioSnapshot(
            id=uuid.uuid4(),
            captured_at=datetime.now(UTC),
            total_value=total_value,
            cash=cash,
            positions=[{k: v for k, v in p.items()} for p in positions],
            allocation=allocation,
        )
        session.add(snapshot)
        await session.commit()
        return snapshot

    async def _fetch_portfolio_inputs(
        self,
    ) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
        return await asyncio.gather(
            self.order_adapter.portfolio_positions(self.account_id),
            self.account_adapter.account_summary(self.account_id),
            self.account_adapter.account_ledger(self.account_id),
        )

    @staticmethod
    async def list_snapshots(
        session: AsyncSession, *, limit: int = 50, offset: int = 0
    ) -> list[PortfolioSnapshot]:
        stmt = (
            select(PortfolioSnapshot)
            .order_by(PortfolioSnapshot.captured_at.desc())
            .offset(offset)
            .limit(limit)
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    def _build_positions(
        raw_positions: list[dict[str, Any]],
        summary: dict[str, Any],
        ledger: dict[str, Any],
    ) -> list[dict[str, Any]]:
        total_value = safe_float(summary.get("net_liquidation"))
        rates, _notes = estimate_currency_rates(summary, ledger, raw_positions)

        positions = []
        for pos in raw_positions:
            if not pos.get("position"):
                continue
            currency = str(pos.get("currency") or BASE_CURRENCY).upper()
            native_market_value = safe_float(pos.get("mktValue"))
            market_value_base, fx_rate_to_base, fx_rate_source = convert_native_to_base(
                native_market_value,
                currency,
                rates,
            )
            native_market_price = safe_float(pos.get("mktPrice"))
            market_price_base, _, _ = convert_native_to_base(
                native_market_price,
                currency,
                rates,
            )
            allocation_pct = (market_value_base / total_value * 100) if total_value else 0
            positions.append(
                {
                    "conid": pos.get("conid"),
                    "symbol": pos.get("contractDesc") or pos.get("ticker", ""),
                    "position": pos.get("position"),
                    "market_price": native_market_price,
                    "market_price_base": round(market_price_base, 4),
                    "market_value": native_market_value,
                    "market_value_base": round(market_value_base, 2),
                    "average_cost": pos.get("avgCost"),
                    "unrealized_pnl": pos.get("unrealizedPnl"),
                    "realized_pnl": pos.get("realizedPnl"),
                    "allocation_pct": round(allocation_pct, 2),
                    "currency": currency,
                    "base_currency": BASE_CURRENCY,
                    "fx_rate_to_base": round(fx_rate_to_base, 6),
                    "fx_rate_source": fx_rate_source,
                    "asset_class": pos.get("assetClass"),
                }
            )
        return positions

    @staticmethod
    def _build_summary(
        account: dict[str, Any],
        ledger: dict[str, Any],
        positions: list[dict[str, Any]],
    ) -> dict[str, Any]:
        rates, notes = estimate_currency_rates(account, ledger, positions)
        return {
            "net_liquidation": account.get("net_liquidation"),
            "total_cash": account.get("total_cash"),
            "buying_power": account.get("buying_power"),
            "gross_position_value": account.get("gross_position_value"),
            "excess_liquidity": account.get("excess_liquidity"),
            "base_currency": BASE_CURRENCY,
            "fx_rates": summarize_fx_sources(rates),
            "fx_notes": notes,
            "positions_count": len(positions),
            "top_holdings": sorted(
                positions,
                key=lambda p: abs(safe_float(p.get("market_value_base"))),
                reverse=True,
            )[:5],
        }
