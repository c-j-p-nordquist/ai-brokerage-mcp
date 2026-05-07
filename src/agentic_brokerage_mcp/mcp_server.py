from __future__ import annotations

import logging

from mcp.server.fastmcp import FastMCP

from agentic_brokerage_mcp.config import settings

mcp = FastMCP(
    "agentic-brokerage-mcp",
    instructions=(
        "Opinionated brokerage workflow tools for Interactive Brokers Client Portal/iBeam. "
        f"Account-level values use the configured base currency ({settings.base_currency}); "
        "positions and order prices use each instrument's native currency. "
        "Use ibkr_session(ensure=True) after auth errors. Resolve options with option_chain or "
        "search_option_contracts before get_option_greeks. submit_order defaults to dry-run "
        "bracket previews, position_size is advisory sizing only, and mutating operations are "
        "audited. Live broker submission requires explicit server configuration."
    ),
)


def _register_tools() -> None:
    from agentic_brokerage_mcp.tools import audit, market_data, orders, portfolio, risk, watchlist
    from agentic_brokerage_mcp.tools import session as session_tools

    audit.register(mcp)
    market_data.register(mcp)
    orders.register(mcp)
    portfolio.register(mcp)
    risk.register(mcp)
    session_tools.register(mcp)
    watchlist.register(mcp)


def main() -> None:
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )
    _register_tools()
    mcp.run()


if __name__ == "__main__":
    main()
