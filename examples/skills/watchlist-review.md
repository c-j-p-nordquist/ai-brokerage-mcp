# Watchlist Review Prompt

Review watchlist entries without changing them unless the user approves the exact update.

1. Call `manage_watchlist` with `action="list"`.
2. For in-scope symbols, call `market` and compare current context with the stored rationale and target levels.
3. Classify each item as ready, still watching, or consider dropping.
4. Propose status updates in plain language. Wait for explicit approval before calling `manage_watchlist` with `action="update"` or `action="remove"`.
