from __future__ import annotations

from typing import Any

from agentic_brokerage_mcp.ibkr.market_data import IBKRMarketDataAdapter


class NewsService:
    def __init__(self, market_data: IBKRMarketDataAdapter):
        self.market_data = market_data

    async def headlines(
        self,
        symbol: str,
        *,
        count: int = 20,
        conid: str | None = None,
    ) -> dict[str, Any]:
        contract = await self.market_data.resolve_contract(symbol, conid=conid)
        articles = await self.market_data.get_news_headlines(contract.conid, count=count)
        return {
            "symbol": symbol.upper(),
            "conid": contract.conid,
            "exchange": contract.exchange,
            "currency": contract.currency,
            "count": len(articles),
            "articles": articles,
        }

    async def article(self, article_id: str) -> dict[str, Any]:
        return await self.market_data.get_news_article(article_id)
