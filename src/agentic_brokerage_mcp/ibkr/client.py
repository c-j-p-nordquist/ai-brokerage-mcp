from __future__ import annotations

import asyncio
import logging
from collections import deque
from dataclasses import dataclass
from time import monotonic
from typing import Any, Literal

import httpx

logger = logging.getLogger("agentic_brokerage_mcp.ibkr.client")

_RETRY_BACKOFF_BASE_S = 0.5
_RETRY_STATUS_CODES = frozenset({503})
_RATE_LIMIT_BACKOFF_S: tuple[float, ...] = (10.0, 30.0, 60.0)


class IBKRClientError(RuntimeError):
    """Transport or protocol error against the IBKR Web API."""


class IBKRApiError(IBKRClientError):
    def __init__(self, status_code: int, message: str, payload: Any | None = None):
        super().__init__(f"IBKR API {status_code}: {message}")
        self.status_code = status_code
        self.payload = payload


class IBKRTransientError(IBKRClientError):
    """Retryable server error (503 etc.)."""


class RateLimiter:
    def __init__(self, max_requests: int, window_seconds: float = 1.0):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._timestamps: deque[float] = deque()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        while True:
            async with self._lock:
                now = monotonic()
                while self._timestamps and now - self._timestamps[0] >= self.window_seconds:
                    self._timestamps.popleft()
                if len(self._timestamps) < self.max_requests:
                    self._timestamps.append(now)
                    return
                sleep_for = self.window_seconds - (now - self._timestamps[0])
            await asyncio.sleep(max(sleep_for, 0.0))


@dataclass(slots=True)
class IBKRClientConfig:
    base_url: str = "https://127.0.0.1:5001/v1/api"
    timeout_seconds: float = 15.0
    verify_ssl: bool = False
    max_requests_per_second: int = 10
    max_retries: int = 3
    account_id: str = ""


class IBKRClient:
    def __init__(
        self,
        config: IBKRClientConfig | None = None,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.config = config or IBKRClientConfig()
        self._client = httpx.AsyncClient(
            base_url=self.config.base_url.rstrip("/"),
            timeout=self.config.timeout_seconds,
            verify=self.config.verify_ssl,
            transport=transport,
        )
        self._rate_limiter = RateLimiter(self.config.max_requests_per_second)
        self._order_lock = asyncio.Lock()

    async def close(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> IBKRClient:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    async def request(
        self,
        method: Literal["GET", "POST", "DELETE", "PUT"],
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | list[Any] | None = None,
        require_order_serialization: bool = False,
    ) -> Any:
        if require_order_serialization:
            async with self._order_lock:
                return await self._request(method, path, params=params, json=json)
        return await self._request(method, path, params=params, json=json)

    async def _request(
        self,
        method: Literal["GET", "POST", "DELETE", "PUT"],
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | list[Any] | None = None,
    ) -> Any:
        last_exc: Exception | None = None
        max_attempts = max(self.config.max_retries, len(_RATE_LIMIT_BACKOFF_S))

        for attempt in range(1, max_attempts + 1):
            await self._rate_limiter.acquire()
            try:
                response = await self._client.request(method, path, params=params, json=json)
            except httpx.HTTPError as exc:
                raise IBKRClientError(f"IBKR transport error: {exc}") from exc

            if response.status_code in _RETRY_STATUS_CODES:
                backoff = _RETRY_BACKOFF_BASE_S * (2 ** (attempt - 1))
                logger.warning(
                    "Transient %d from %s %s (attempt %d/%d), retrying in %.1fs",
                    response.status_code,
                    method,
                    path,
                    attempt,
                    self.config.max_retries,
                    backoff,
                )
                last_exc = IBKRTransientError(
                    f"{response.status_code} from {method} {path} (attempt {attempt})"
                )
                if attempt < self.config.max_retries:
                    await asyncio.sleep(backoff)
                    continue
                raise last_exc

            if response.status_code == 429:
                backoff = _RATE_LIMIT_BACKOFF_S[min(attempt - 1, len(_RATE_LIMIT_BACKOFF_S) - 1)]
                payload = self._decode(response)
                message = self._extract_error(payload)
                logger.warning(
                    "Rate-limited (429) on %s %s (attempt %d), backing off %.0fs",
                    method,
                    path,
                    attempt,
                    backoff,
                )
                last_exc = IBKRApiError(response.status_code, message, payload)
                await asyncio.sleep(backoff)
                if attempt < len(_RATE_LIMIT_BACKOFF_S):
                    continue
                raise last_exc

            payload = self._decode(response)
            if response.status_code >= 400:
                raise IBKRApiError(response.status_code, self._extract_error(payload), payload)
            return payload

        raise last_exc or IBKRTransientError(f"Retries exhausted for {method} {path}")

    def require_account_id(self) -> str:
        account_id = self.config.account_id.strip()
        if not account_id:
            raise ValueError("IBKR account_id is required")
        return account_id

    @staticmethod
    def _extract_error(payload: Any) -> str:
        if isinstance(payload, dict):
            for key in ("error", "message"):
                value = payload.get(key)
                if isinstance(value, str) and value:
                    return value
        if isinstance(payload, list) and payload:
            first = payload[0]
            if isinstance(first, dict):
                for key in ("error", "message"):
                    value = first.get(key)
                    if isinstance(value, str) and value:
                        return value
        return "unknown error"

    @staticmethod
    def _decode(response: httpx.Response) -> Any:
        if not response.content:
            return {}
        try:
            return response.json()
        except ValueError:
            return response.text
