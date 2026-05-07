from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from agentic_brokerage_mcp.ibkr.client import IBKRClient
from agentic_brokerage_mcp.models import IBKRSessionStatus

logger = logging.getLogger("agentic_brokerage_mcp.ibkr.session")


def _utcnow() -> datetime:
    return datetime.now(UTC)


class IBKRSessionManager:
    def __init__(self, client: IBKRClient, tickle_interval_seconds: float = 60.0):
        self.client = client
        self.tickle_interval = timedelta(seconds=tickle_interval_seconds)
        self._last_tickle_at: datetime | None = None

    async def ensure_session(self) -> IBKRSessionStatus:
        status = await self.auth_status()
        if status.authenticated and status.connected and not status.competing:
            await self._tickle_if_due()
            return status

        if status.competing:
            logger.warning("IBKR session is competing; reinitializing")

        await self.client.request(
            "POST", "/iserver/auth/ssodh/init", json={"publish": True, "compete": True}
        )
        status = await self.auth_status()
        if not status.authenticated or not status.connected or status.competing:
            message = status.message or "authentication failed"
            if status.competing:
                message = f"session still competing after reinit: {message}"
            raise RuntimeError(f"IBKR session unavailable: {message}")
        await self._tickle_if_due(force=True)
        return status

    async def auth_status(self) -> IBKRSessionStatus:
        payload = await self.client.request("POST", "/iserver/auth/status", json={})
        return self._parse_status(payload)

    async def tickle(self) -> dict[str, Any]:
        payload = await self.client.request("POST", "/tickle", json={})
        self._last_tickle_at = _utcnow()
        return payload

    async def get_accounts(self) -> list[str]:
        payload = await self.client.request("GET", "/iserver/accounts")
        if isinstance(payload, dict):
            accounts = payload.get("accounts")
            if isinstance(accounts, list):
                return [str(a) for a in accounts]
        if isinstance(payload, list):
            return [str(a) for a in payload]
        return []

    async def set_account(self, account_id: str) -> dict[str, Any]:
        payload = await self.client.request("POST", "/iserver/account", json={"acctId": account_id})
        return payload if isinstance(payload, dict) else {"result": payload}

    async def suppress_order_confirmations(self) -> None:
        safe_ids = [
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
        ]
        try:
            await self.client.request(
                "POST", "/iserver/questions/suppress", json={"messageIds": safe_ids}
            )
        except Exception as exc:
            logger.warning("Failed to suppress order confirmations: %s", exc)

    async def _tickle_if_due(self, *, force: bool = False) -> None:
        now = _utcnow()
        if not force and self._last_tickle_at and now - self._last_tickle_at < self.tickle_interval:
            return
        await self.tickle()

    @staticmethod
    def _parse_status(payload: dict[str, Any]) -> IBKRSessionStatus:
        return IBKRSessionStatus(
            authenticated=bool(payload.get("authenticated")),
            connected=bool(payload.get("connected")),
            competing=bool(payload.get("competing")),
            message=str(payload.get("message", "")),
            last_checked_at=_utcnow(),
            sso_expires_ms=payload.get("ssoExpires"),
        )
