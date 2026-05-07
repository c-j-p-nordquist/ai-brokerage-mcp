from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agentic_brokerage_mcp.db.models import OrderHistory
from agentic_brokerage_mcp.ibkr.account import IBKRAccountAdapter
from agentic_brokerage_mcp.ibkr.market_data import IBKRContract, IBKRMarketDataAdapter
from agentic_brokerage_mcp.ibkr.orders import IBKROrderAdapter
from agentic_brokerage_mcp.services.valuation import BASE_CURRENCY, safe_float


class OrderService:
    def __init__(
        self,
        order_adapter: IBKROrderAdapter,
        market_data: IBKRMarketDataAdapter,
        account_adapter: IBKRAccountAdapter,
        account_id: str,
    ):
        self.order_adapter = order_adapter
        self.market_data = market_data
        self.account_adapter = account_adapter
        self.account_id = account_id

    async def submit(
        self,
        *,
        session: AsyncSession,
        symbol: str,
        side: str,
        quantity: float,
        order_type: str = "MKT",
        price: float | None = None,
        stop_price: float | None = None,
        tif: str = "DAY",
        outside_rth: bool = False,
        agent_id: str | None = None,
        conid: str | None = None,
        client_order_id: str | None = None,
        sec_type: str = "STK",
        expiry: str | None = None,
        strike: float | None = None,
        right: str | None = None,
        exchange: str | None = None,
        underlying_conid: str | None = None,
    ) -> dict[str, Any]:
        request_payload = self._single_order_request(
            symbol=symbol,
            side=side,
            quantity=quantity,
            order_type=order_type,
            price=price,
            stop_price=stop_price,
            tif=tif,
            outside_rth=outside_rth,
            client_order_id=client_order_id,
            sec_type=sec_type,
            expiry=expiry,
            strike=strike,
            right=right,
            exchange=exchange,
            underlying_conid=underlying_conid,
        )
        if client_order_id:
            existing = await self._find_by_client_order_id(session, client_order_id)
            if existing is not None:
                self._ensure_matching_request(existing, request_payload)
                return self._stored_response(existing)

        contract = await self._resolve_trade_contract(
            symbol=symbol,
            sec_type=sec_type,
            conid=conid,
            expiry=expiry,
            strike=strike,
            right=right,
            exchange=exchange,
            underlying_conid=underlying_conid,
        )
        result = await self.order_adapter.submit_order(
            account_id=self.account_id,
            conid=int(contract.conid),
            side=side.upper(),
            order_type=order_type,
            quantity=quantity,
            price=price,
            stop_price=stop_price,
            tif=tif,
            outside_rth=outside_rth,
            client_order_id=client_order_id,
        )
        response_payload = {
            "order_id": result["order_id"],
            "symbol": symbol.upper(),
            "conid": contract.conid,
            "side": side.upper(),
            "order_type": order_type,
            "quantity": quantity,
            "price": price,
            "stop_price": stop_price,
            "status": result.get("status", "Submitted"),
            "outside_rth": outside_rth,
            "client_order_id": client_order_id,
            "asset_class": contract.asset_class,
            "exchange": contract.exchange,
            "currency": contract.currency,
            "expiry": contract.expiry or expiry,
            "strike": contract.strike if contract.strike is not None else strike,
            "right": contract.right or (right.upper() if right else None),
            "multiplier": self._contract_multiplier(contract),
            "underlying_conid": contract.underlying_conid or underlying_conid,
        }
        session.add(
            OrderHistory(
                id=uuid.uuid4(),
                created_at=datetime.now(UTC),
                ibkr_order_id=result["order_id"],
                conid=contract.conid,
                symbol=symbol.upper(),
                side=side.upper(),
                order_type=order_type,
                quantity=quantity,
                price=price,
                stop_price=stop_price,
                status=result.get("status", "Submitted"),
                client_order_id=client_order_id,
                raw_response={
                    "request": {**request_payload, "conid": contract.conid},
                    "response": response_payload,
                    "ibkr": result.get("raw"),
                },
                agent_id=agent_id,
            )
        )
        await session.commit()
        return response_payload

    async def submit_bracket(
        self,
        *,
        session: AsyncSession,
        symbol: str,
        side: str,
        quantity: float,
        entry_price: float,
        stop_price: float,
        target_price: float | None = None,
        tif: str = "DAY",
        outside_rth: bool = False,
        agent_id: str | None = None,
        conid: str | None = None,
        client_order_id: str | None = None,
        sec_type: str = "STK",
        expiry: str | None = None,
        strike: float | None = None,
        right: str | None = None,
        exchange: str | None = None,
        underlying_conid: str | None = None,
    ) -> dict[str, Any]:
        request_payload = self._bracket_order_request(
            symbol=symbol,
            side=side,
            quantity=quantity,
            entry_price=entry_price,
            stop_price=stop_price,
            target_price=target_price,
            tif=tif,
            outside_rth=outside_rth,
            client_order_id=client_order_id,
            sec_type=sec_type,
            expiry=expiry,
            strike=strike,
            right=right,
            exchange=exchange,
            underlying_conid=underlying_conid,
        )
        if client_order_id:
            existing = await self._find_by_client_order_id(session, client_order_id)
            if existing is not None:
                self._ensure_matching_request(existing, request_payload)
                return self._stored_response(existing)

        contract = await self._resolve_trade_contract(
            symbol=symbol,
            sec_type=sec_type,
            conid=conid,
            expiry=expiry,
            strike=strike,
            right=right,
            exchange=exchange,
            underlying_conid=underlying_conid,
        )
        result = await self.order_adapter.submit_bracket_order(
            account_id=self.account_id,
            conid=int(contract.conid),
            side=side.upper(),
            quantity=quantity,
            entry_price=entry_price,
            stop_price=stop_price,
            target_price=target_price,
            tif=tif,
            outside_rth=outside_rth,
            client_order_id=client_order_id,
        )
        response_payload = {
            "parent_order_id": result["parent_order_id"],
            "child_order_ids": result.get("child_order_ids", []),
            "symbol": symbol.upper(),
            "conid": contract.conid,
            "side": side.upper(),
            "quantity": quantity,
            "entry_price": entry_price,
            "stop_price": stop_price,
            "target_price": target_price,
            "status": result.get("status", "Submitted"),
            "outside_rth": outside_rth,
            "client_order_id": client_order_id,
            "asset_class": contract.asset_class,
            "exchange": contract.exchange,
            "currency": contract.currency,
            "expiry": contract.expiry or expiry,
            "strike": contract.strike if contract.strike is not None else strike,
            "right": contract.right or (right.upper() if right else None),
            "multiplier": self._contract_multiplier(contract),
            "underlying_conid": contract.underlying_conid or underlying_conid,
        }
        session.add(
            OrderHistory(
                id=uuid.uuid4(),
                created_at=datetime.now(UTC),
                ibkr_order_id=result["parent_order_id"],
                conid=contract.conid,
                symbol=symbol.upper(),
                side=side.upper(),
                order_type="BRACKET",
                quantity=quantity,
                price=entry_price,
                stop_price=stop_price,
                status=result.get("status", "Submitted"),
                client_order_id=client_order_id,
                raw_response={
                    "request": {**request_payload, "conid": contract.conid},
                    "response": response_payload,
                    "ibkr": result.get("raw"),
                },
                agent_id=agent_id,
            )
        )
        await session.commit()
        return response_payload

    async def preview(
        self,
        *,
        symbol: str,
        side: str,
        quantity: float,
        order_type: str = "MKT",
        price: float | None = None,
        stop_price: float | None = None,
        tif: str = "DAY",
        outside_rth: bool = False,
        conid: str | None = None,
        sec_type: str = "STK",
        expiry: str | None = None,
        strike: float | None = None,
        right: str | None = None,
        exchange: str | None = None,
        underlying_conid: str | None = None,
    ) -> dict[str, Any]:
        contract, summary, positions, live_orders = await self._preview_context(
            symbol=symbol,
            conid=conid,
            sec_type=sec_type,
            expiry=expiry,
            strike=strike,
            right=right,
            exchange=exchange,
            underlying_conid=underlying_conid,
        )
        return await self._preview_from_context(
            contract=contract,
            summary=summary,
            positions=positions,
            live_orders=live_orders,
            symbol=symbol,
            side=side,
            quantity=quantity,
            order_type=order_type,
            price=price,
            stop_price=stop_price,
            tif=tif,
            outside_rth=outside_rth,
        )

    async def preview_bracket(
        self,
        *,
        symbol: str,
        side: str,
        quantity: float,
        entry_price: float,
        stop_price: float,
        target_price: float | None = None,
        tif: str = "DAY",
        outside_rth: bool = False,
        conid: str | None = None,
        sec_type: str = "STK",
        expiry: str | None = None,
        strike: float | None = None,
        right: str | None = None,
        exchange: str | None = None,
        underlying_conid: str | None = None,
    ) -> dict[str, Any]:
        contract, summary, positions, live_orders = await self._preview_context(
            symbol=symbol,
            conid=conid,
            sec_type=sec_type,
            expiry=expiry,
            strike=strike,
            right=right,
            exchange=exchange,
            underlying_conid=underlying_conid,
        )
        return await self._preview_bracket_from_context(
            contract=contract,
            summary=summary,
            positions=positions,
            live_orders=live_orders,
            symbol=symbol,
            side=side,
            quantity=quantity,
            entry_price=entry_price,
            stop_price=stop_price,
            target_price=target_price,
            tif=tif,
            outside_rth=outside_rth,
        )

    async def _preview_from_context(
        self,
        *,
        contract: IBKRContract,
        summary: dict[str, Any],
        positions: list[dict[str, Any]],
        live_orders: list[dict[str, Any]],
        symbol: str,
        side: str,
        quantity: float,
        order_type: str = "MKT",
        price: float | None = None,
        stop_price: float | None = None,
        tif: str = "DAY",
        outside_rth: bool = False,
    ) -> dict[str, Any]:
        last_price = await self._resolve_last_price(contract.conid)
        estimated_fill_price = self._estimate_fill_price(
            order_type=order_type,
            last_price=last_price,
            price=price,
            stop_price=stop_price,
        )
        contract_multiplier = self._contract_multiplier(contract)
        position_unit = "contracts" if contract.asset_class.upper() == "OPT" else "shares"
        fx_rate, fx_rate_source = self._estimate_base_to_quote_rate(
            summary,
            positions,
            quote_currency=contract.currency,
        )
        current_position = next(
            (p for p in positions if p["conid"] == contract.conid or p["symbol"] == symbol.upper()),
            None,
        )
        current_position_units = float(current_position["position"]) if current_position else 0.0
        pending_buy_units, pending_sell_units = self._pending_shares_for_symbol(
            symbol.upper(), contract.conid, live_orders
        )
        matching_live_orders = self._matching_live_orders(
            symbol.upper(), contract.conid, live_orders
        )
        effective_current_units = current_position_units + pending_buy_units - pending_sell_units
        post_trade_position_units = (
            effective_current_units + quantity
            if side.upper() == "BUY"
            else effective_current_units - quantity
        )
        estimated_notional_quote = (
            round(quantity * contract_multiplier * estimated_fill_price, 2)
            if estimated_fill_price is not None
            else None
        )
        estimated_notional_base = (
            round(estimated_notional_quote * fx_rate, 2)
            if estimated_notional_quote is not None
            else None
        )

        warnings = self._preview_warnings(
            side=side,
            quantity=quantity,
            effective_current_quantity=effective_current_units,
            matching_live_orders=matching_live_orders,
            estimated_fill_price=estimated_fill_price,
            estimated_notional_base=estimated_notional_base,
            account_cash_base=float(summary.get("total_cash", 0) or 0),
            position_label=position_unit,
        )

        return {
            "symbol": symbol.upper(),
            "conid": contract.conid,
            "exchange": contract.exchange,
            "asset_class": contract.asset_class,
            "currency": contract.currency,
            "expiry": contract.expiry or None,
            "strike": contract.strike,
            "right": contract.right or None,
            "contract_multiplier": contract_multiplier,
            "position_unit": position_unit,
            "side": side.upper(),
            "quantity": quantity,
            "order_type": order_type,
            "price": price,
            "stop_price": stop_price,
            "tif": tif,
            "outside_rth": outside_rth,
            "last_price": last_price,
            "estimated_fill_price": estimated_fill_price,
            "estimated_notional_quote": estimated_notional_quote,
            "estimated_notional_base": estimated_notional_base,
            "base_to_quote_rate": round(fx_rate, 4),
            "base_to_quote_rate_source": fx_rate_source,
            "account_cash_base": round(float(summary.get("total_cash", 0) or 0), 2),
            "current_position_shares": current_position_units,
            "pending_buy_shares": pending_buy_units,
            "pending_sell_shares": pending_sell_units,
            "post_trade_position_shares": post_trade_position_units,
            "current_position_units": current_position_units,
            "pending_buy_units": pending_buy_units,
            "pending_sell_units": pending_sell_units,
            "post_trade_position_units": post_trade_position_units,
            "matching_live_orders": matching_live_orders,
            "underlying_conid": contract.underlying_conid or None,
            "warnings": warnings,
        }

    async def _preview_bracket_from_context(
        self,
        *,
        contract: IBKRContract,
        summary: dict[str, Any],
        positions: list[dict[str, Any]],
        live_orders: list[dict[str, Any]],
        symbol: str,
        side: str,
        quantity: float,
        entry_price: float,
        stop_price: float,
        target_price: float | None = None,
        tif: str = "DAY",
        outside_rth: bool = False,
    ) -> dict[str, Any]:
        preview = await self._preview_from_context(
            contract=contract,
            summary=summary,
            positions=positions,
            live_orders=live_orders,
            symbol=symbol,
            side=side,
            quantity=quantity,
            order_type="LMT",
            price=entry_price,
            stop_price=stop_price,
            tif=tif,
            outside_rth=outside_rth,
        )
        risk_per_unit_quote = abs(entry_price - stop_price)
        risk_per_contract_quote = round(
            risk_per_unit_quote * float(preview["contract_multiplier"]), 4
        )
        estimated_max_loss_quote = round(risk_per_contract_quote * quantity, 2)
        estimated_max_loss_base = round(
            estimated_max_loss_quote * float(preview["base_to_quote_rate"]),
            2,
        )

        estimated_max_reward_quote = None
        estimated_max_reward_base = None
        risk_reward_ratio = None
        reward_per_unit_quote = None
        reward_per_contract_quote = None
        if target_price is not None:
            reward_per_unit_quote = abs(target_price - entry_price)
            reward_per_contract_quote = round(
                reward_per_unit_quote * float(preview["contract_multiplier"]),
                4,
            )
            estimated_max_reward_quote = round(reward_per_contract_quote * quantity, 2)
            estimated_max_reward_base = round(
                estimated_max_reward_quote * float(preview["base_to_quote_rate"]),
                2,
            )
            if risk_per_unit_quote > 0:
                risk_reward_ratio = round(reward_per_unit_quote / risk_per_unit_quote, 2)

        preview.update(
            {
                "order_type": "BRACKET",
                "entry_price": entry_price,
                "stop_price": stop_price,
                "target_price": target_price,
                "estimated_entry_notional_quote": round(
                    entry_price * quantity * float(preview["contract_multiplier"]),
                    2,
                ),
                "estimated_entry_notional_base": round(
                    entry_price
                    * quantity
                    * float(preview["contract_multiplier"])
                    * float(preview["base_to_quote_rate"]),
                    2,
                ),
                "risk_per_share_quote": round(risk_per_unit_quote, 4),
                "risk_per_unit_quote": round(risk_per_unit_quote, 4),
                "risk_per_contract_quote": risk_per_contract_quote,
                "estimated_max_loss_quote": estimated_max_loss_quote,
                "estimated_max_loss_base": estimated_max_loss_base,
                "reward_per_unit_quote": round(reward_per_unit_quote, 4)
                if reward_per_unit_quote is not None
                else None,
                "reward_per_contract_quote": reward_per_contract_quote,
                "estimated_max_reward_quote": estimated_max_reward_quote,
                "estimated_max_reward_base": estimated_max_reward_base,
                "risk_reward_ratio": risk_reward_ratio,
            }
        )
        return preview

    async def modify(self, *, order_id: str, modifications: dict[str, Any]) -> list[dict[str, Any]]:
        return await self.order_adapter.modify_order(
            account_id=self.account_id, order_id=order_id, modifications=modifications
        )

    async def cancel(self, *, order_id: str) -> dict[str, Any]:
        return await self.order_adapter.cancel_order(account_id=self.account_id, order_id=order_id)

    async def live_orders(self) -> dict[str, Any]:
        return await self.order_adapter.live_orders()

    async def recent_trades(self) -> list[dict[str, Any]]:
        return await self.order_adapter.recent_trades()

    @staticmethod
    async def order_history(
        session: AsyncSession, *, symbol: str | None = None, limit: int = 100, offset: int = 0
    ) -> list[OrderHistory]:
        stmt = select(OrderHistory).order_by(OrderHistory.created_at.desc())
        if symbol:
            stmt = stmt.where(OrderHistory.symbol == symbol.upper())
        stmt = stmt.offset(offset).limit(limit)
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def _preview_context(
        self,
        *,
        symbol: str,
        conid: str | None,
        sec_type: str = "STK",
        expiry: str | None = None,
        strike: float | None = None,
        right: str | None = None,
        exchange: str | None = None,
        underlying_conid: str | None = None,
    ) -> tuple[IBKRContract, dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
        contract, summary, raw_positions, live_orders_payload = await asyncio.gather(
            self._resolve_trade_contract(
                symbol=symbol,
                sec_type=sec_type,
                conid=conid,
                expiry=expiry,
                strike=strike,
                right=right,
                exchange=exchange,
                underlying_conid=underlying_conid,
            ),
            self.account_adapter.account_summary(self.account_id),
            self.order_adapter.portfolio_positions(self.account_id),
            self.order_adapter.live_orders(),
        )
        positions = self._normalize_positions(raw_positions)
        live_orders = self._normalize_live_orders(live_orders_payload)
        return contract, summary, positions, live_orders

    async def _resolve_last_price(self, conid: str) -> float | None:
        quotes = await self.market_data.get_quotes([conid])
        if quotes:
            last_price = safe_float(quotes[0].get("31"))
            if last_price > 0:
                return round(last_price, 4)

        bars = await self.market_data.get_historical_bars(conid=conid, period="1M", bar="1d")
        if bars:
            return round(float(bars[-1].close), 4)

        return None

    @staticmethod
    def _estimate_fill_price(
        *,
        order_type: str,
        last_price: float | None,
        price: float | None,
        stop_price: float | None,
    ) -> float | None:
        if order_type == "MKT":
            return last_price
        if order_type == "LMT":
            return price
        if order_type == "STP":
            return price
        if order_type == "STP_LMT":
            return price or stop_price
        return last_price

    @staticmethod
    def _estimate_base_to_quote_rate(
        summary: dict[str, Any],
        positions: list[dict[str, Any]],
        *,
        quote_currency: str | None = None,
    ) -> tuple[float, str]:
        normalized_quote_currency = str(quote_currency or "").upper()
        if normalized_quote_currency == BASE_CURRENCY:
            return 1.0, "base_currency"

        gross_position_value = float(summary.get("gross_position_value", 0) or 0)
        positions_with_currency = [p for p in positions if p.get("currency")]
        if positions_with_currency:
            base_native_total = sum(
                abs(p["market_value"])
                for p in positions_with_currency
                if str(p.get("currency") or "").upper() == BASE_CURRENCY
            )
            foreign_native_total = sum(
                abs(p["market_value"])
                for p in positions_with_currency
                if str(p.get("currency") or "").upper() != BASE_CURRENCY
            )
            foreign_value_budget = max(gross_position_value - base_native_total, 0.0)
            matching_native_total = sum(
                abs(p["market_value"])
                for p in positions_with_currency
                if str(p.get("currency") or "").upper() == normalized_quote_currency
            )
            if foreign_value_budget > 0 and matching_native_total > 0:
                return (
                    foreign_value_budget / matching_native_total,
                    "currency_specific_portfolio_implied",
                )
            if foreign_value_budget > 0 and foreign_native_total > 0:
                return (
                    foreign_value_budget / foreign_native_total,
                    "blended_foreign_portfolio_implied",
                )

        native_position_total = sum(abs(p["market_value"]) for p in positions if p["market_value"])
        if gross_position_value > 0 and native_position_total > 0:
            return gross_position_value / native_position_total, "portfolio_implied"
        return 1.0, "assumed_1.0"

    @staticmethod
    def _normalize_positions(raw_positions: list[dict[str, Any]]) -> list[dict[str, Any]]:
        positions = []
        for pos in raw_positions:
            symbol = str(pos.get("contractDesc") or pos.get("ticker") or "").upper()
            if not symbol:
                continue
            positions.append(
                {
                    "symbol": symbol,
                    "conid": str(pos.get("conid", "")),
                    "position": float(pos.get("position", 0) or 0),
                    "market_value": float(pos.get("mktValue", 0) or 0),
                    "currency": str(pos.get("currency") or ""),
                }
            )
        return positions

    @staticmethod
    def _normalize_live_orders(payload: Any) -> list[dict[str, Any]]:
        if isinstance(payload, dict):
            if isinstance(payload.get("orders"), list):
                return [item for item in payload["orders"] if isinstance(item, dict)]
            if isinstance(payload.get("data"), list):
                return [item for item in payload["data"] if isinstance(item, dict)]
            return []
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        return []

    @staticmethod
    def _pending_shares_for_symbol(
        symbol: str, conid: str, live_orders: list[dict[str, Any]]
    ) -> tuple[float, float]:
        pending_buy_shares = 0.0
        pending_sell_shares = 0.0
        for order in live_orders:
            status = str(order.get("status") or order.get("order_status") or "").lower()
            if status in {"filled", "cancelled", "inactive"}:
                continue
            order_symbol = str(
                order.get("ticker") or order.get("symbol") or order.get("contractDesc") or ""
            ).upper()
            order_conid = str(order.get("conid") or "")
            if order_symbol != symbol and order_conid != conid:
                continue
            qty = OrderService._order_quantity(order)
            if qty <= 0:
                continue
            side = str(order.get("side") or "").upper()
            if side in {"BUY", "B"}:
                pending_buy_shares += qty
            elif side in {"SELL", "S"}:
                pending_sell_shares += qty
        return pending_buy_shares, pending_sell_shares

    @staticmethod
    def _matching_live_orders(
        symbol: str,
        conid: str,
        live_orders: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        matches = []
        for order in live_orders:
            status = str(order.get("status") or order.get("order_status") or "").lower()
            if status in {"filled", "cancelled", "inactive"}:
                continue
            order_symbol = str(
                order.get("ticker") or order.get("symbol") or order.get("contractDesc") or ""
            ).upper()
            order_conid = str(order.get("conid") or "")
            if order_symbol != symbol and order_conid != conid:
                continue
            matches.append(
                {
                    "order_id": str(order.get("orderId") or order.get("order_id") or ""),
                    "side": str(order.get("side") or "").upper(),
                    "status": str(order.get("status") or order.get("order_status") or ""),
                    "remaining_quantity": OrderService._order_quantity(order),
                }
            )
        return matches

    @staticmethod
    def _order_quantity(order: dict[str, Any]) -> float:
        for key in ("remainingQuantity", "remainingSize", "quantity", "totalSize", "size"):
            raw_qty = order.get(key)
            if raw_qty is None:
                continue
            try:
                return float(raw_qty)
            except (TypeError, ValueError):
                continue
        return 0.0

    @staticmethod
    def _preview_warnings(
        *,
        side: str,
        quantity: float,
        effective_current_quantity: float,
        matching_live_orders: list[dict[str, Any]],
        estimated_fill_price: float | None,
        estimated_notional_base: float | None,
        account_cash_base: float,
        position_label: str,
    ) -> list[str]:
        warnings = []
        if matching_live_orders:
            warnings.append("Matching live orders already exist for this contract.")
        if side.upper() == "SELL" and quantity > max(effective_current_quantity, 0.0):
            warnings.append(
                f"Sell quantity exceeds the current net long {position_label} and may "
                "open or increase a short."
            )
        if estimated_fill_price is None:
            warnings.append("Could not estimate a fill price from current market data.")
        if (
            side.upper() == "BUY"
            and estimated_notional_base is not None
            and account_cash_base > 0
            and estimated_notional_base > account_cash_base
        ):
            warnings.append(
                "Estimated notional exceeds current cash balance. Margin may still make "
                "the order valid."
            )
        return warnings

    @staticmethod
    def _single_order_request(
        *,
        symbol: str,
        side: str,
        quantity: float,
        order_type: str,
        price: float | None,
        stop_price: float | None,
        tif: str,
        outside_rth: bool,
        client_order_id: str | None,
        sec_type: str,
        expiry: str | None,
        strike: float | None,
        right: str | None,
        exchange: str | None,
        underlying_conid: str | None,
    ) -> dict[str, Any]:
        return {
            "symbol": symbol.upper(),
            "side": side.upper(),
            "quantity": quantity,
            "order_type": order_type,
            "price": price,
            "stop_price": stop_price,
            "tif": tif,
            "outside_rth": outside_rth,
            "client_order_id": client_order_id,
            "sec_type": sec_type.upper(),
            "expiry": expiry,
            "strike": strike,
            "right": right.upper() if right else None,
            "exchange": exchange,
            "underlying_conid": underlying_conid,
        }

    @staticmethod
    def _bracket_order_request(
        *,
        symbol: str,
        side: str,
        quantity: float,
        entry_price: float,
        stop_price: float,
        target_price: float | None,
        tif: str,
        outside_rth: bool,
        client_order_id: str | None,
        sec_type: str,
        expiry: str | None,
        strike: float | None,
        right: str | None,
        exchange: str | None,
        underlying_conid: str | None,
    ) -> dict[str, Any]:
        return {
            "symbol": symbol.upper(),
            "side": side.upper(),
            "quantity": quantity,
            "order_type": "BRACKET",
            "entry_price": entry_price,
            "stop_price": stop_price,
            "target_price": target_price,
            "tif": tif,
            "outside_rth": outside_rth,
            "client_order_id": client_order_id,
            "sec_type": sec_type.upper(),
            "expiry": expiry,
            "strike": strike,
            "right": right.upper() if right else None,
            "exchange": exchange,
            "underlying_conid": underlying_conid,
        }

    @staticmethod
    def _stored_response(record: OrderHistory) -> dict[str, Any]:
        if isinstance(record.raw_response, dict):
            response = record.raw_response.get("response")
            if isinstance(response, dict):
                return response

        fallback = {
            "symbol": record.symbol,
            "conid": record.conid,
            "side": record.side,
            "order_type": record.order_type,
            "quantity": float(record.quantity),
            "price": float(record.price) if record.price is not None else None,
            "stop_price": float(record.stop_price) if record.stop_price is not None else None,
            "status": record.status,
            "outside_rth": None,
            "client_order_id": record.client_order_id,
        }
        if record.order_type == "BRACKET":
            fallback["parent_order_id"] = record.ibkr_order_id
        else:
            fallback["order_id"] = record.ibkr_order_id
        return fallback

    @staticmethod
    def _ensure_matching_request(record: OrderHistory, current_request: dict[str, Any]) -> None:
        if not isinstance(record.raw_response, dict):
            return
        stored_request = record.raw_response.get("request")
        if not isinstance(stored_request, dict):
            return

        comparable_keys = (
            "symbol",
            "side",
            "quantity",
            "order_type",
            "price",
            "stop_price",
            "entry_price",
            "target_price",
            "tif",
            "outside_rth",
            "sec_type",
            "expiry",
            "strike",
            "right",
            "exchange",
            "underlying_conid",
        )
        if any(stored_request.get(key) != current_request.get(key) for key in comparable_keys):
            raise ValueError(
                f"client_order_id '{record.client_order_id}' was already used for a "
                "different order."
            )

    @staticmethod
    async def _find_by_client_order_id(
        session: AsyncSession,
        client_order_id: str,
    ) -> OrderHistory | None:
        stmt = (
            select(OrderHistory)
            .where(OrderHistory.client_order_id == client_order_id)
            .order_by(OrderHistory.created_at.desc())
            .limit(1)
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def _resolve_trade_contract(
        self,
        *,
        symbol: str,
        sec_type: str,
        conid: str | None,
        expiry: str | None,
        strike: float | None,
        right: str | None,
        exchange: str | None,
        underlying_conid: str | None,
    ) -> IBKRContract:
        normalized_sec_type = sec_type.upper()
        if normalized_sec_type != "OPT":
            return await self.market_data.resolve_contract(
                symbol, sec_type=normalized_sec_type, conid=conid
            )

        if conid is not None and expiry is None and strike is None and right is None:
            return IBKRContract(
                conid=str(conid),
                symbol=symbol.upper(),
                exchange=exchange or "",
                asset_class="OPT",
                multiplier="100",
                underlying_conid=underlying_conid or "",
            )

        missing = [
            name
            for name, value in (("expiry", expiry), ("strike", strike), ("right", right))
            if value is None
        ]
        if missing:
            raise ValueError(
                "Option orders require expiry, strike, and right unless an option conid "
                "is supplied."
            )
        normalized_right = str(right).upper()
        if normalized_right not in {"C", "P"}:
            raise ValueError("Option right must be 'C' or 'P'.")

        return await self.market_data.resolve_option_contract(
            symbol,
            expiry=str(expiry),
            strike=float(strike),
            right=normalized_right,
            exchange=exchange,
            underlying_conid=underlying_conid,
            conid=conid,
            sec_type=normalized_sec_type,
        )

    @staticmethod
    def _contract_multiplier(contract: IBKRContract) -> float:
        if contract.multiplier:
            try:
                value = float(contract.multiplier)
            except (TypeError, ValueError):
                value = 0.0
            if value > 0:
                return value
        return 100.0 if contract.asset_class.upper() == "OPT" else 1.0
