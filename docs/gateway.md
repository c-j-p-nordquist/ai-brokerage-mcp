# Client Portal Gateway

Live mode requires an authenticated Interactive Brokers Client Portal-compatible gateway. This project does not ship, configure, or supervise that gateway. It only expects a reachable HTTPS base URL and an account id.

Demo mode does not need a gateway.

## Integration Contract

The MCP server sends Client Portal Web API requests to:

```bash
AGENTIC_BROKERAGE_MCP_IBKR_BASE_URL=https://localhost:5001/v1/api
```

The default URL matches the common HTTPS gateway port exposed by iBeam. If you run the official gateway directly, set this value to whatever host, port, and base path your gateway exposes.

Minimum read-only live configuration:

```bash
AGENTIC_BROKERAGE_MCP_BROKER_MODE=live
AGENTIC_BROKERAGE_MCP_IBKR_BASE_URL=https://localhost:5001/v1/api
AGENTIC_BROKERAGE_MCP_IBKR_ACCOUNT_ID=YOUR_ACCOUNT_ID
AGENTIC_BROKERAGE_MCP_ENABLE_LIVE_TRADING=false
```

Order submit, cancel, and modify calls remain blocked until you explicitly set:

```bash
AGENTIC_BROKERAGE_MCP_ENABLE_LIVE_TRADING=true
```

## Gateway Options

### Official Client Portal Gateway

Use the official Client Portal Gateway if you want the smallest dependency chain and are comfortable launching and authenticating the gateway yourself. Interactive Brokers documents the gateway setup, Java requirement, local launch scripts, browser login, session constraints, and certificate behavior in its Client Portal API materials:

- [Interactive Brokers: Launching and Authenticating the Gateway](https://www.interactivebrokers.com/campus/trading-lessons/launching-and-authenticating-the-gateway/)
- [Interactive Brokers: Web API Documentation](https://www.interactivebrokers.com/campus/ibkr-api-page/webapi-doc/)

The important operational point for this MCP server is that authentication is external. Start and authenticate the gateway first, then run the MCP server in `live` mode.

### iBeam

iBeam is an optional third-party authentication and maintenance tool around the Client Portal Web API Gateway. It can be useful when you want a containerized gateway process with automated startup and session maintenance.

Use iBeam if that tradeoff fits your setup, but do not treat it as part of this project or as a hard dependency:

- [Voyz/iBeam on GitHub](https://github.com/Voyz/ibeam)

iBeam requires broker credentials to be available to its runtime. That is a real security boundary. Do not commit iBeam environment files, compose overrides, screenshots, logs, cookies, certificates, or account identifiers to this repo.

## Local Verification

After your gateway is running and authenticated, check the gateway directly before involving an MCP client:

```bash
curl -k "$AGENTIC_BROKERAGE_MCP_IBKR_BASE_URL/iserver/auth/status"
```

Then run the MCP server:

```bash
AGENTIC_BROKERAGE_MCP_BROKER_MODE=live uv run agentic-brokerage-mcp
```

If `ibkr_session` reports an authentication problem, fix the gateway session first. The MCP can check or reinitialize a session through the API, but it does not replace the gateway login flow.

## Operational Notes

- Keep demo mode as the default for tests and examples.
- Prefer paper trading credentials while validating a gateway setup.
- Avoid sharing one account session across multiple active trading clients.
- Keep gateway credentials and session artifacts outside the repository.
- Leave `AGENTIC_BROKERAGE_MCP_ENABLE_LIVE_TRADING=false` until your MCP client workflow requires an explicit human approval step after dry-run previews.
