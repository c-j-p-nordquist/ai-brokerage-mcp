from __future__ import annotations

from agentic_brokerage_mcp.config import settings
from agentic_brokerage_mcp.ibkr.account import IBKRAccountAdapter
from agentic_brokerage_mcp.ibkr.client import IBKRClient, IBKRClientConfig
from agentic_brokerage_mcp.ibkr.market_data import IBKRMarketDataAdapter
from agentic_brokerage_mcp.ibkr.orders import IBKROrderAdapter
from agentic_brokerage_mcp.ibkr.session import IBKRSessionManager
from agentic_brokerage_mcp.mock import (
    MockAccountAdapter,
    MockMarketDataAdapter,
    MockOrderAdapter,
    MockSessionManager,
)

_ibkr_client: IBKRClient | None = None
_session_manager: IBKRSessionManager | MockSessionManager | None = None
_order_adapter: IBKROrderAdapter | MockOrderAdapter | None = None
_market_data_adapter: IBKRMarketDataAdapter | MockMarketDataAdapter | None = None
_account_adapter: IBKRAccountAdapter | MockAccountAdapter | None = None


def get_ibkr_client() -> IBKRClient:
    if settings.broker_mode == "demo":
        raise RuntimeError("The live Interactive Brokers client is unavailable in demo mode.")
    global _ibkr_client
    if _ibkr_client is None:
        config = IBKRClientConfig(
            base_url=settings.ibkr_base_url,
            account_id=settings.ibkr_account_id,
            verify_ssl=settings.ibkr_verify_ssl,
        )
        _ibkr_client = IBKRClient(config)
    return _ibkr_client


def get_session_manager() -> IBKRSessionManager | MockSessionManager:
    global _session_manager
    if _session_manager is None:
        if settings.broker_mode == "demo":
            _session_manager = MockSessionManager()
        else:
            _session_manager = IBKRSessionManager(get_ibkr_client())
    return _session_manager


def get_order_adapter() -> IBKROrderAdapter | MockOrderAdapter:
    global _order_adapter
    if _order_adapter is None:
        if settings.broker_mode == "demo":
            _order_adapter = MockOrderAdapter()
        else:
            _order_adapter = IBKROrderAdapter(get_ibkr_client(), get_session_manager())
    return _order_adapter


def get_market_data_adapter() -> IBKRMarketDataAdapter | MockMarketDataAdapter:
    global _market_data_adapter
    if _market_data_adapter is None:
        if settings.broker_mode == "demo":
            _market_data_adapter = MockMarketDataAdapter()
        else:
            _market_data_adapter = IBKRMarketDataAdapter(get_ibkr_client(), get_session_manager())
    return _market_data_adapter


def get_account_adapter() -> IBKRAccountAdapter | MockAccountAdapter:
    global _account_adapter
    if _account_adapter is None:
        if settings.broker_mode == "demo":
            _account_adapter = MockAccountAdapter()
        else:
            _account_adapter = IBKRAccountAdapter(get_ibkr_client(), get_session_manager())
    return _account_adapter


async def shutdown_ibkr() -> None:
    global _ibkr_client
    if _ibkr_client:
        await _ibkr_client.close()
        _ibkr_client = None
