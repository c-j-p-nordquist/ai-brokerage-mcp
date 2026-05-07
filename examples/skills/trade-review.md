# Trade Review Prompt

Use the MCP tools as a human-in-the-loop workflow. Never submit a live order until the user explicitly approves a dry-run preview in the conversation.

1. Call `portfolio` to understand cash, concentration, existing exposure, live orders, and recent activity.
2. Call `market` for the symbol. If the market context contradicts the idea, stop and explain the risk.
3. Call `position_size` to produce baseline risk sizing. Treat it as advisory, not authority.
4. Call `submit_order` with `dry_run=true`. Prefer a bracket preview when entry, stop, and target are known.
5. Present entry, stop, target, estimated max loss, account impact, concentration risks, and open-order conflicts.
6. Only after explicit approval, call `submit_order` with `dry_run=false`. In live mode this still requires the server-side live-trading flag.
