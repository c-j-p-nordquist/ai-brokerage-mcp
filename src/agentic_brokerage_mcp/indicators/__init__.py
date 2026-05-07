from __future__ import annotations

from collections.abc import Sequence

import pandas as pd
from ta.momentum import RSIIndicator, StochRSIIndicator
from ta.trend import MACD, ADXIndicator, EMAIndicator, SMAIndicator
from ta.volatility import AverageTrueRange, BollingerBands

from agentic_brokerage_mcp.ibkr.market_data import BarData

PriceInput = Sequence[BarData] | pd.Series | pd.DataFrame
OHLCInput = Sequence[BarData] | pd.DataFrame


def sma(data: PriceInput, window: int = 20) -> pd.Series:
    return SMAIndicator(_close_series(data), window=window).sma_indicator()


def ema(data: PriceInput, window: int = 12) -> pd.Series:
    return EMAIndicator(_close_series(data), window=window).ema_indicator()


def rsi(data: PriceInput, window: int = 14) -> pd.Series:
    return RSIIndicator(_close_series(data), window=window).rsi()


def atr(data: OHLCInput, window: int = 14) -> pd.Series:
    frame = _ohlc_frame(data)
    return AverageTrueRange(
        frame["high"],
        frame["low"],
        frame["close"],
        window=window,
    ).average_true_range()


def macd(data: PriceInput) -> dict[str, pd.Series]:
    obj = MACD(_close_series(data))
    return {
        "macd": obj.macd(),
        "signal": obj.macd_signal(),
        "histogram": obj.macd_diff(),
    }


def bollinger(data: PriceInput, window: int = 20) -> dict[str, pd.Series]:
    obj = BollingerBands(_close_series(data), window=window)
    return {
        "upper": obj.bollinger_hband(),
        "middle": obj.bollinger_mavg(),
        "lower": obj.bollinger_lband(),
    }


def slope(data: PriceInput, window: int = 200) -> float | None:
    values = [float(value) for value in _close_series(data).dropna().tail(window)]
    if len(values) < 2:
        return None

    xs = list(range(len(values)))
    x_mean = sum(xs) / len(xs)
    y_mean = sum(values) / len(values)
    denominator = sum((x - x_mean) ** 2 for x in xs)
    if denominator == 0:
        return None

    numerator = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, values, strict=True))
    return round(numerator / denominator, 4)


def adx(data: OHLCInput, window: int = 14) -> dict[str, pd.Series]:
    frame = _ohlc_frame(data)
    obj = ADXIndicator(frame["high"], frame["low"], frame["close"], window=window)
    return {
        "adx": obj.adx(),
        "plus_di": obj.adx_pos(),
        "minus_di": obj.adx_neg(),
    }


def stochrsi(data: PriceInput, window: int = 14) -> dict[str, pd.Series]:
    obj = StochRSIIndicator(_close_series(data), window=window)
    return {
        "k": obj.stochrsi_k(),
        "d": obj.stochrsi_d(),
    }


def _last(series: pd.Series) -> float | None:
    val = series.dropna()
    if val.empty:
        return None
    return round(float(val.iloc[-1]), 4)


def _tail(series: pd.Series, n: int = 5) -> list[float | None]:
    vals = series.dropna().tail(n)
    return [round(float(v), 4) for v in vals]


def _close_series(data: PriceInput) -> pd.Series:
    if isinstance(data, pd.Series):
        return data.astype(float)
    if isinstance(data, pd.DataFrame):
        return data["close"].astype(float)
    return pd.Series([bar.close for bar in data], dtype=float)


def _ohlc_frame(data: OHLCInput) -> pd.DataFrame:
    if isinstance(data, pd.DataFrame):
        return data[["high", "low", "close"]].astype(float)
    return pd.DataFrame(
        [{"high": bar.high, "low": bar.low, "close": bar.close} for bar in data],
        columns=["high", "low", "close"],
        dtype=float,
    )
