from __future__ import annotations

from typing import Any

from agentic_brokerage_mcp.ibkr.client import IBKRClient
from agentic_brokerage_mcp.ibkr.session import IBKRSessionManager


class IBKRAccountAdapter:
    def __init__(self, client: IBKRClient, session: IBKRSessionManager):
        self.client = client
        self.session = session

    async def account_summary(self, account_id: str) -> dict[str, Any]:
        await self.session.ensure_session()
        payload = await self.client.request("GET", f"/portfolio/{account_id}/summary")
        if not isinstance(payload, dict):
            return {}
        return self._flatten_summary(payload)

    async def account_ledger(self, account_id: str) -> dict[str, Any]:
        await self.session.ensure_session()
        payload = await self.client.request("GET", f"/portfolio/{account_id}/ledger")
        return payload if isinstance(payload, dict) else {}

    @staticmethod
    def _flatten_summary(raw: dict[str, Any]) -> dict[str, Any]:
        """Extract key values from the nested IBKR summary format.

        IBKR returns {key: {amount: X, ...}}; we flatten to {key: X}.
        """
        result: dict[str, Any] = {}
        key_map = {
            "availablefunds": "available_funds",
            "buyingpower": "buying_power",
            "netliquidation": "net_liquidation",
            "grosspositionvalue": "gross_position_value",
            "totalcashvalue": "total_cash",
            "maintmarginreq": "maintenance_margin",
            "initmarginreq": "initial_margin",
            "excessliquidity": "excess_liquidity",
            "cushion": "cushion",
        }
        for ibkr_key, friendly_key in key_map.items():
            entry = raw.get(ibkr_key)
            if isinstance(entry, dict):
                result[friendly_key] = entry.get("amount")
            elif entry is not None:
                result[friendly_key] = entry
        return result
