from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

from agentic_brokerage_mcp.dependencies import get_session_manager


def register(mcp: FastMCP) -> None:

    @mcp.tool()
    async def ibkr_session(ensure: bool = False) -> dict:
        """Check the gateway session or reinitialize it after auth issues."""
        sm = get_session_manager()
        if ensure:
            status = await sm.ensure_session()
            return {
                "authenticated": status.authenticated,
                "connected": status.connected,
                "message": status.message,
            }
        status = await sm.auth_status()
        return {
            "authenticated": status.authenticated,
            "connected": status.connected,
            "competing": status.competing,
            "message": status.message,
            "sso_expires_ms": status.sso_expires_ms,
        }
