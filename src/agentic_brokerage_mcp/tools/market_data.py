from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

from agentic_brokerage_mcp.dependencies import get_market_data_adapter
from agentic_brokerage_mcp.services.analysis import AnalysisService
from agentic_brokerage_mcp.services.market_data import MarketDataService
from agentic_brokerage_mcp.services.news import NewsService


def _analysis_svc() -> AnalysisService:
    return AnalysisService(get_market_data_adapter())


def _market_svc() -> MarketDataService:
    return MarketDataService(get_market_data_adapter())


def _news_svc() -> NewsService:
    return NewsService(get_market_data_adapter())


def register(mcp: FastMCP) -> None:

    @mcp.tool()
    async def market(
        symbol: str,
        period: str = "3M",
        bar: str = "1d",
        news_count: int = 5,
        conid: str | None = None,
        sec_type: str = "STK",
        expiry: str | None = None,
        strike: float | None = None,
        right: str | None = None,
        exchange: str | None = None,
        underlying_conid: str | None = None,
    ) -> dict:
        """Return technical context and recent news for a symbol."""
        analysis, news = await asyncio.gather(
            _analysis_svc().summary(
                symbol,
                period=period,
                bar=bar,
                conid=conid,
                sec_type=sec_type,
                expiry=expiry,
                strike=strike,
                right=right,
                exchange=exchange,
                underlying_conid=underlying_conid,
            ),
            _news_svc().headlines(symbol, count=news_count, conid=conid),
        )
        return {**analysis, "news": news.get("articles", [])}

    @mcp.tool()
    async def search_symbol(query: str, sec_type: str | None = "STK") -> list:
        """Search IBKR contracts by symbol or company name."""
        return await _market_svc().search(query, sec_type=sec_type)

    @mcp.tool()
    async def option_chain(
        symbol: str,
        expiry: str | None = None,
        exchange: str | None = None,
        underlying_conid: str | None = None,
        min_strike: float | None = None,
        max_strike: float | None = None,
        strike_limit: int = 20,
    ) -> dict:
        """List option expiry months or strikes for a requested expiry."""
        return await _market_svc().option_chain(
            symbol,
            expiry=expiry,
            exchange=exchange,
            underlying_conid=underlying_conid,
            min_strike=min_strike,
            max_strike=max_strike,
            strike_limit=strike_limit,
        )

    @mcp.tool()
    async def search_option_contracts(
        symbol: str,
        expiry: str,
        strike: float,
        right: str,
        exchange: str | None = None,
        underlying_conid: str | None = None,
    ) -> list:
        """Resolve exact option contracts for expiry, strike, and right."""
        return await _market_svc().option_contracts(
            symbol,
            expiry=expiry,
            strike=strike,
            right=right,
            exchange=exchange,
            underlying_conid=underlying_conid,
        )

    @mcp.tool()
    async def get_option_greeks(
        symbol: str,
        expiry: str | None = None,
        strike: float | None = None,
        right: str | None = None,
        exchange: str | None = None,
        underlying_conid: str | None = None,
        conid: str | None = None,
    ) -> dict:
        """Return greeks and related market data for an option contract."""
        return await _market_svc().option_greeks(
            symbol,
            expiry=expiry,
            strike=strike,
            right=right,
            exchange=exchange,
            underlying_conid=underlying_conid,
            conid=conid,
        )
