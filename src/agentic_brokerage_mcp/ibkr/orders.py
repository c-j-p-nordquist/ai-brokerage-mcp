from __future__ import annotations

import logging
from typing import Any
from uuid import uuid4

from agentic_brokerage_mcp.ibkr.client import IBKRClient
from agentic_brokerage_mcp.ibkr.session import IBKRSessionManager

logger = logging.getLogger("agentic_brokerage_mcp.ibkr.orders")

_MAX_CONFIRM_ROUNDS = 5
_SAFE_CONFIRM_MESSAGE_IDS = frozenset(
    {
        "o163",
        "o354",
        "o382",
        "o383",
        "o403",
        "o451",
        "o10101",
        "o10151",
        "o10152",
        "o10153",
    }
)


class IBKROrderAdapter:
    def __init__(self, client: IBKRClient, session: IBKRSessionManager):
        self.client = client
        self.session = session

    async def submit_order(
        self,
        *,
        account_id: str,
        conid: int,
        side: str,
        order_type: str = "MKT",
        quantity: float,
        price: float | None = None,
        stop_price: float | None = None,
        tif: str = "DAY",
        outside_rth: bool = False,
        client_order_id: str | None = None,
    ) -> dict[str, Any]:
        await self.session.ensure_session()
        ibkr_order_type = "STP LMT" if order_type == "STP_LMT" else order_type
        order_body: dict[str, Any] = {
            "acctId": account_id,
            "conid": conid,
            "side": side.upper(),
            "orderType": ibkr_order_type,
            "tif": tif,
            "quantity": quantity,
            "outsideRTH": outside_rth,
        }
        if client_order_id:
            order_body["cOID"] = client_order_id
        if order_type == "LMT" and price is not None:
            order_body["price"] = price
        elif order_type == "STP" and price is not None:
            order_body["auxPrice"] = price
        elif order_type == "STP_LMT":
            if price is not None:
                order_body["price"] = price  # limit price (worst fill)
            if stop_price is not None:
                order_body["auxPrice"] = stop_price  # stop trigger

        payload = await self.client.request(
            "POST",
            f"/iserver/account/{account_id}/orders",
            json={"orders": [order_body]},
            require_order_serialization=True,
        )
        self._check_error(payload, "order")
        resolved = await self._resolve_replies(payload)
        return self._extract_order_result(resolved)

    async def submit_bracket_order(
        self,
        *,
        account_id: str,
        conid: int,
        side: str,
        quantity: float,
        entry_price: float,
        stop_price: float,
        target_price: float | None = None,
        tif: str = "DAY",
        outside_rth: bool = False,
        client_order_id: str | None = None,
    ) -> dict[str, Any]:
        await self.session.ensure_session()
        parent_coid = client_order_id or f"inv-{side[0].lower()}-{uuid4().hex[:12]}"
        exit_side = "SELL" if side.upper() == "BUY" else "BUY"

        parent: dict[str, Any] = {
            "acctId": account_id,
            "conid": conid,
            "side": side.upper(),
            "orderType": "LMT",
            "tif": tif,
            "quantity": quantity,
            "price": entry_price,
            "outsideRTH": outside_rth,
            "cOID": parent_coid,
        }
        stop_child: dict[str, Any] = {
            "acctId": account_id,
            "conid": conid,
            "parentId": parent_coid,
            "isSingleGroup": True,
            "side": exit_side,
            "orderType": "STP",
            "tif": "GTC",
            "quantity": quantity,
            "auxPrice": stop_price,
            "outsideRTH": outside_rth,
        }
        legs = [parent, stop_child]
        if target_price is not None:
            tp_child: dict[str, Any] = {
                "acctId": account_id,
                "conid": conid,
                "parentId": parent_coid,
                "isSingleGroup": True,
                "side": exit_side,
                "orderType": "LMT",
                "tif": "GTC",
                "quantity": quantity,
                "price": target_price,
                "outsideRTH": outside_rth,
            }
            legs.append(tp_child)

        payload = await self.client.request(
            "POST",
            f"/iserver/account/{account_id}/orders",
            json={"orders": legs},
            require_order_serialization=True,
        )
        self._check_error(payload, "bracket order")
        resolved = await self._resolve_replies(payload)
        return self._extract_bracket_result(resolved)

    async def modify_order(
        self,
        *,
        account_id: str,
        order_id: str,
        modifications: dict[str, Any],
    ) -> list[dict[str, Any]]:
        await self.session.ensure_session()
        payload = await self.client.request(
            "POST",
            f"/iserver/account/{account_id}/order/{order_id}",
            json=modifications,
            require_order_serialization=True,
        )
        return await self._resolve_replies(payload)

    async def cancel_order(self, *, account_id: str, order_id: str) -> dict[str, Any]:
        await self.session.ensure_session()
        result = await self.client.request(
            "DELETE",
            f"/iserver/account/{account_id}/order/{order_id}",
            require_order_serialization=True,
        )
        return result if isinstance(result, dict) else {"result": result}

    async def live_orders(self) -> dict[str, Any]:
        await self.session.ensure_session()
        return await self.client.request("GET", "/iserver/account/orders")

    async def portfolio_positions(self, account_id: str) -> list[dict[str, Any]]:
        await self.session.ensure_session()
        try:
            await self.client.request("POST", f"/portfolio/{account_id}/positions/invalidate")
        except Exception:
            pass
        result = await self.client.request("GET", f"/portfolio/{account_id}/positions/0")
        return result if isinstance(result, list) else []

    async def recent_trades(self) -> list[dict[str, Any]]:
        await self.session.ensure_session()
        result = await self.client.request("GET", "/iserver/account/trades")
        if isinstance(result, list):
            return [item for item in result if isinstance(item, dict)]
        if isinstance(result, dict):
            trades = result.get("trades", [])
            if isinstance(trades, list):
                return [item for item in trades if isinstance(item, dict)]
        return []

    async def _resolve_replies(self, payload: Any) -> list[dict[str, Any]]:
        current = payload
        if isinstance(current, dict):
            current = [current]

        for round_num in range(_MAX_CONFIRM_ROUNDS):
            if not isinstance(current, list) or not current:
                raise RuntimeError(f"Unexpected order response: {current!r}")

            needs_reply = [item for item in current if isinstance(item, dict) and "id" in item]
            if not needs_reply:
                return current

            for item in needs_reply:
                message_ids = item.get("messageIds", [])
                if not message_ids:
                    raise RuntimeError(
                        f"IBKR prompt without messageIds: {item.get('message', item)}"
                    )
                unknown = set(message_ids) - _SAFE_CONFIRM_MESSAGE_IDS
                if unknown:
                    raise RuntimeError(
                        f"IBKR order requires manual confirmation: {item.get('message', unknown)}"
                    )
                reply_id = str(item["id"])
                logger.info("Confirming order reply (round %d, id=%s)", round_num + 1, reply_id)
                current = await self.client.request(
                    "POST",
                    f"/iserver/reply/{reply_id}",
                    json={"confirmed": True},
                    require_order_serialization=True,
                )
                if isinstance(current, dict):
                    current = [current]

        logger.warning("Order confirmation exceeded %d rounds", _MAX_CONFIRM_ROUNDS)
        return current if isinstance(current, list) else [current]

    @staticmethod
    def _check_error(payload: Any, context: str) -> None:
        if isinstance(payload, list) and payload:
            first = payload[0] if isinstance(payload[0], dict) else {}
            err = first.get("error")
            if err:
                raise RuntimeError(f"IBKR {context} rejected: {err}")
        elif isinstance(payload, dict):
            err = payload.get("error")
            if err:
                raise RuntimeError(f"IBKR {context} rejected: {err}")

    @staticmethod
    def _extract_order_result(resolved: list[dict[str, Any]]) -> dict[str, Any]:
        first = resolved[0] if resolved else {}
        raw_id = first.get("order_id") or first.get("orderId")
        if raw_id is None or str(raw_id) == "-1":
            error_msg = first.get("error") or first.get("message") or first.get("text") or ""
            raise RuntimeError(f"IBKR order missing order_id: {error_msg or resolved}")
        return {
            "order_id": str(raw_id),
            "status": first.get("order_status", "Submitted"),
            "raw": resolved,
        }

    @staticmethod
    def _extract_bracket_result(resolved: list[dict[str, Any]]) -> dict[str, Any]:
        order_ids = []
        for item in resolved:
            if not isinstance(item, dict):
                continue
            raw_id = item.get("order_id") or item.get("orderId")
            if raw_id is not None and str(raw_id) != "-1":
                order_ids.append(str(raw_id))
        if not order_ids:
            raise RuntimeError(f"IBKR bracket order missing order_ids: {resolved}")
        return {
            "parent_order_id": order_ids[0],
            "child_order_ids": order_ids[1:],
            "status": resolved[0].get("order_status", "Submitted") if resolved else "Unknown",
            "raw": resolved,
        }
