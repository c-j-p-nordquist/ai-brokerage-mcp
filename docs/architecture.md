# Architecture

```mermaid
flowchart TD
    Client["MCP client<br/>Codex, Claude Desktop, or another agent host"]
    Server["agentic-brokerage-mcp<br/>FastMCP stdio server"]
    Tools["Workflow tools<br/>portfolio, market, position_size, submit_order, audit"]
    Services["Service layer<br/>risk, portfolio, orders, market data, watchlist"]
    Store["SQLite audit/watchlist/order history"]
    Demo["Demo adapters<br/>synthetic account, prices, orders"]
    Live["Client Portal-compatible gateway<br/>live adapter"]

    Client --> Server --> Tools --> Services
    Services --> Store
    Services --> Demo
    Services --> Live
```

The server intentionally exposes a small workflow surface instead of a raw endpoint mirror. Agents get tools with stable, task-oriented contracts; broker-specific details stay inside adapters and services.

## Safety Boundary

`submit_order` defaults to `dry_run=true`. In `live` mode, any real submit, cancel, or modify operation also requires `AGENTIC_BROKERAGE_MCP_ENABLE_LIVE_TRADING=true`. Demo mode can simulate mutations without a broker connection.

Mutating actions write an audit record to SQLite. The audit log is part of the public API through the `audit` tool so an agent or operator can inspect recent actions and their parameters.
