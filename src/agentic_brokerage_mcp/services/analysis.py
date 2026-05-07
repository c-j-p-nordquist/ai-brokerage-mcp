from __future__ import annotations

from typing import Any

import pandas as pd

from agentic_brokerage_mcp.ibkr.market_data import IBKRContract, IBKRMarketDataAdapter
from agentic_brokerage_mcp.indicators import (
    _last,
    _tail,
    adx,
    atr,
    bollinger,
    ema,
    macd,
    rsi,
    sma,
    stochrsi,
)

__all__ = ["AnalysisService", "_last", "_tail"]


class AnalysisService:
    def __init__(self, market_data: IBKRMarketDataAdapter):
        self.market_data = market_data

    async def indicators(
        self,
        symbol: str,
        *,
        period: str = "3M",
        bar: str = "1d",
        indicator_list: list[str] | None = None,
        conid: str | None = None,
        sec_type: str = "STK",
        expiry: str | None = None,
        strike: float | None = None,
        right: str | None = None,
        exchange: str | None = None,
        underlying_conid: str | None = None,
    ) -> dict[str, Any]:
        contract = await self._resolve_contract(
            symbol,
            conid=conid,
            sec_type=sec_type,
            expiry=expiry,
            strike=strike,
            right=right,
            exchange=exchange,
            underlying_conid=underlying_conid,
        )
        bars = await self.market_data.get_historical_bars(
            conid=contract.conid, period=period, bar=bar
        )
        if not bars:
            return {"symbol": symbol.upper(), "error": "no data", "indicators": {}}

        df = pd.DataFrame(
            [
                {
                    "ts": b.timestamp,
                    "open": b.open,
                    "high": b.high,
                    "low": b.low,
                    "close": b.close,
                    "volume": b.volume,
                }
                for b in bars
            ]
        )
        df.set_index("ts", inplace=True)

        requested = indicator_list or [
            "sma_20",
            "sma_50",
            "ema_12",
            "rsi_14",
            "macd",
            "bb_20",
            "atr_14",
        ]
        results: dict[str, Any] = {}

        for ind in requested:
            try:
                results[ind] = self._compute(df, ind)
            except Exception as e:
                results[ind] = {"error": str(e)}

        return {
            "symbol": symbol.upper(),
            "conid": contract.conid,
            "asset_class": contract.asset_class,
            "exchange": contract.exchange,
            "currency": contract.currency,
            "expiry": contract.expiry or None,
            "strike": contract.strike,
            "right": contract.right or None,
            "period": period,
            "bar": bar,
            "data_points": len(df),
            "indicators": results,
        }

    async def summary(
        self,
        symbol: str,
        *,
        period: str = "3M",
        bar: str = "1d",
        conid: str | None = None,
        sec_type: str = "STK",
        expiry: str | None = None,
        strike: float | None = None,
        right: str | None = None,
        exchange: str | None = None,
        underlying_conid: str | None = None,
    ) -> dict[str, Any]:
        contract = await self._resolve_contract(
            symbol,
            conid=conid,
            sec_type=sec_type,
            expiry=expiry,
            strike=strike,
            right=right,
            exchange=exchange,
            underlying_conid=underlying_conid,
        )
        bars = await self.market_data.get_historical_bars(
            conid=contract.conid, period=period, bar=bar
        )
        if not bars:
            return {"symbol": symbol.upper(), "error": "no data"}

        df = pd.DataFrame(
            [
                {
                    "ts": b.timestamp,
                    "open": b.open,
                    "high": b.high,
                    "low": b.low,
                    "close": b.close,
                    "volume": b.volume,
                }
                for b in bars
            ]
        )
        df.set_index("ts", inplace=True)
        close = df["close"]
        last = float(close.iloc[-1])

        sma_20 = sma(close, window=20)
        sma_50 = sma(close, window=50)
        rsi_14 = rsi(close, window=14)
        macd_result = macd(close)
        bb = bollinger(close, window=20)
        atr_14 = atr(df, window=14)

        sma20_val = _last(sma_20)
        sma50_val = _last(sma_50)
        rsi_val = _last(rsi_14)

        if sma20_val and sma50_val:
            if last > sma20_val > sma50_val:
                trend = "bullish"
            elif last < sma20_val < sma50_val:
                trend = "bearish"
            else:
                trend = "neutral"
        else:
            trend = "insufficient_data"

        if rsi_val is not None:
            if rsi_val > 70:
                momentum = "overbought"
            elif rsi_val < 30:
                momentum = "oversold"
            else:
                momentum = "neutral"
        else:
            momentum = "unknown"

        return {
            "symbol": symbol.upper(),
            "conid": contract.conid,
            "asset_class": contract.asset_class,
            "exchange": contract.exchange,
            "currency": contract.currency,
            "expiry": contract.expiry or None,
            "strike": contract.strike,
            "right": contract.right or None,
            "last_price": last,
            "trend": trend,
            "momentum": momentum,
            "sma_20": sma20_val,
            "sma_50": sma50_val,
            "rsi_14": rsi_val,
            "macd": _last(macd_result["macd"]),
            "macd_signal": _last(macd_result["signal"]),
            "bb_upper": _last(bb["upper"]),
            "bb_lower": _last(bb["lower"]),
            "atr_14": _last(atr_14),
            "support": _last(bb["lower"]),
            "resistance": _last(bb["upper"]),
            "data_points": len(df),
        }

    async def _resolve_contract(
        self,
        symbol: str,
        *,
        conid: str | None,
        sec_type: str,
        expiry: str | None,
        strike: float | None,
        right: str | None,
        exchange: str | None,
        underlying_conid: str | None,
    ) -> IBKRContract:
        normalized_sec_type = sec_type.upper()
        if normalized_sec_type != "OPT":
            return await self.market_data.resolve_contract(
                symbol, sec_type=normalized_sec_type, conid=conid
            )

        if conid is not None and expiry is None and strike is None and right is None:
            return IBKRContract(
                conid=str(conid),
                symbol=symbol.upper(),
                exchange=exchange or "",
                asset_class="OPT",
                multiplier="100",
                underlying_conid=underlying_conid or "",
            )

        missing = [
            name
            for name, value in (("expiry", expiry), ("strike", strike), ("right", right))
            if value is None
        ]
        if missing:
            raise ValueError(
                "Option analysis requires expiry, strike, and right unless an explicit "
                "option conid is supplied."
            )

        normalized_right = str(right).upper()
        if normalized_right not in {"C", "P"}:
            raise ValueError("Option right must be 'C' or 'P'.")

        return await self.market_data.resolve_option_contract(
            symbol,
            expiry=str(expiry),
            strike=float(strike),
            right=normalized_right,
            exchange=exchange,
            underlying_conid=underlying_conid,
            conid=conid,
            sec_type=normalized_sec_type,
        )

    def _compute(self, df: pd.DataFrame, name: str) -> Any:
        close = df["close"]

        if name.startswith("sma_"):
            window = int(name.split("_")[1])
            series = sma(close, window=window)
            return {"current": _last(series), "values": _tail(series)}

        if name.startswith("ema_"):
            window = int(name.split("_")[1])
            series = ema(close, window=window)
            return {"current": _last(series), "values": _tail(series)}

        if name.startswith("rsi_"):
            window = int(name.split("_")[1])
            series = rsi(close, window=window)
            return {"current": _last(series), "values": _tail(series)}

        if name == "macd":
            result = macd(close)
            return {
                "macd": _last(result["macd"]),
                "signal": _last(result["signal"]),
                "histogram": _last(result["histogram"]),
            }

        if name.startswith("bb_"):
            window = int(name.split("_")[1])
            result = bollinger(close, window=window)
            return {
                "upper": _last(result["upper"]),
                "middle": _last(result["middle"]),
                "lower": _last(result["lower"]),
            }

        if name.startswith("atr_"):
            window = int(name.split("_")[1])
            series = atr(df, window=window)
            return {"current": _last(series), "values": _tail(series)}

        if name == "adx":
            result = adx(df, window=14)
            return {
                "adx": _last(result["adx"]),
                "plus_di": _last(result["plus_di"]),
                "minus_di": _last(result["minus_di"]),
            }

        if name == "stochrsi":
            result = stochrsi(close, window=14)
            return {
                "k": _last(result["k"]),
                "d": _last(result["d"]),
            }

        raise ValueError(f"Unknown indicator: {name}")
