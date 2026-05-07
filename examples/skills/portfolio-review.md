# Portfolio Review Prompt

Review the account without placing or modifying orders.

1. Call `portfolio` with history enabled.
2. Sort positions by absolute allocation.
3. Surface concentration warnings, low cash, currency exposure, live orders, and stale recent activity.
4. For any symbol the user asks about, call `market` for fresh context.
5. Suggest concrete next steps such as running a trade review, canceling an order, or updating the watchlist. Do not submit orders from this workflow.
