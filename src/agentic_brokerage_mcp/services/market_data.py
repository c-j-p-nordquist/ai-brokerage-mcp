from __future__ import annotations

import asyncio
import re
from datetime import datetime
from typing import Any

from agentic_brokerage_mcp.ibkr.market_data import BarData, IBKRContract, IBKRMarketDataAdapter
from agentic_brokerage_mcp.services.valuation import safe_float


class MarketDataService:
    def __init__(self, adapter: IBKRMarketDataAdapter):
        self.adapter = adapter

    async def search(self, query: str, *, sec_type: str | None = "STK") -> list[dict[str, Any]]:
        contracts = await self.adapter.search_contracts(query, sec_type=sec_type)
        ranked = [contract for contract in contracts if contract.conid and contract.conid != "-1"]
        ranked.sort(
            key=lambda contract: (
                contract.symbol.upper() != query.upper(),
                not bool(contract.currency),
                not bool(contract.description),
                str(contract.conid),
            )
        )
        selected = ranked[:20]
        hydrate_jobs = [
            None
            if contract.currency and contract.description
            else self.adapter.resolve_contract(
                contract.symbol,
                sec_type=contract.asset_class or (sec_type or "STK"),
                conid=contract.conid,
            )
            for contract in selected
        ]
        hydrate_results = iter(
            await asyncio.gather(
                *(job for job in hydrate_jobs if job is not None),
                return_exceptions=True,
            )
        )
        hydrated: list[IBKRContract] = []
        for contract, job in zip(selected, hydrate_jobs, strict=False):
            if job is None:
                hydrated.append(contract)
                continue
            result = next(hydrate_results)
            hydrated.append(result if isinstance(result, IBKRContract) else contract)
        hydrated.sort(
            key=lambda contract: (
                contract.symbol.upper() != query.upper(),
                str(contract.currency or "").upper() != "USD",
                str(contract.exchange or "").upper()
                not in {"SMART", "ARCA", "NASDAQ", "NYSE", "AMEX"},
                str(contract.asset_class or "").upper() not in {"STK", "ETF", "IND", "FUND"},
                str(contract.conid),
            )
        )
        return [_contract_dict(c) for c in hydrated]

    async def quotes(self, symbols: list[str]) -> list[dict[str, Any]]:
        resolved_contracts = await asyncio.gather(
            *(self.adapter.resolve_contract(sym) for sym in symbols),
            return_exceptions=True,
        )
        contracts = []
        for sym, resolved in zip(symbols, resolved_contracts, strict=False):
            if isinstance(resolved, Exception):
                contracts.append(IBKRContract(conid="", symbol=sym, exchange="", asset_class=""))
            else:
                contracts.append(resolved)

        valid = [c for c in contracts if c.conid]
        if not valid:
            return []

        raw = await self.adapter.get_quotes([c.conid for c in valid])
        conid_map = {c.conid: c.symbol for c in valid}
        results = []
        for item in raw:
            cid = str(item.get("conid", ""))
            results.append(
                {
                    "conid": cid,
                    "symbol": conid_map.get(cid, ""),
                    "last_price": item.get("31"),
                    "bid": item.get("84"),
                    "ask": item.get("86"),
                    "raw": item,
                }
            )
        return results

    async def history(
        self,
        symbol: str,
        *,
        period: str = "1M",
        bar: str = "1d",
        outside_rth: bool = False,
        conid: str | None = None,
        sec_type: str = "STK",
    ) -> dict[str, Any]:
        contract = await self.adapter.resolve_contract(symbol, sec_type=sec_type, conid=conid)
        bars = await self.adapter.get_historical_bars(
            conid=contract.conid, period=period, bar=bar, outside_rth=outside_rth
        )
        return {
            "symbol": symbol.upper(),
            "conid": contract.conid,
            "exchange": contract.exchange,
            "currency": contract.currency,
            "period": period,
            "bar": bar,
            "count": len(bars),
            "bars": [_bar_dict(b) for b in bars],
        }

    async def option_chain(
        self,
        symbol: str,
        *,
        expiry: str | None = None,
        exchange: str | None = None,
        underlying_conid: str | None = None,
        min_strike: float | None = None,
        max_strike: float | None = None,
        strike_limit: int = 20,
    ) -> dict[str, Any]:
        underlying = await self.adapter.resolve_option_underlying(
            symbol,
            underlying_conid=underlying_conid,
        )
        underlying_price = await _last_price_or_none(self.adapter, underlying.conid)
        chain = {
            "underlying": _contract_dict(underlying),
            "underlying_last_price": underlying_price,
            "expiration_months": list(underlying.option_months),
            "exchange_choices": list(underlying.option_exchanges),
        }
        if expiry is None:
            return chain

        month = _normalize_chain_expiry(expiry)
        strikes = await self.adapter.get_option_strikes(
            underlying_conid=underlying.conid,
            month=month,
            exchange=exchange,
        )
        chain.update(
            {
                "requested_expiry": expiry,
                "expiration_month": month,
                "exchange": exchange,
                "call_strikes": _select_strikes(
                    strikes.get("call", []),
                    center=underlying_price,
                    min_strike=min_strike,
                    max_strike=max_strike,
                    strike_limit=strike_limit,
                ),
                "put_strikes": _select_strikes(
                    strikes.get("put", []),
                    center=underlying_price,
                    min_strike=min_strike,
                    max_strike=max_strike,
                    strike_limit=strike_limit,
                ),
            }
        )
        return chain

    async def option_contracts(
        self,
        symbol: str,
        *,
        expiry: str,
        strike: float,
        right: str,
        exchange: str | None = None,
        underlying_conid: str | None = None,
    ) -> list[dict[str, Any]]:
        contracts = await self.adapter.search_option_contracts(
            symbol,
            expiry=expiry,
            strike=strike,
            right=right,
            exchange=exchange,
            underlying_conid=underlying_conid,
        )
        return [_contract_dict(contract) for contract in contracts]

    async def option_greeks(
        self,
        symbol: str,
        *,
        expiry: str | None = None,
        strike: float | None = None,
        right: str | None = None,
        exchange: str | None = None,
        underlying_conid: str | None = None,
        conid: str | None = None,
    ) -> dict[str, Any]:
        contract = await self._resolve_option_contract(
            symbol,
            expiry=expiry,
            strike=strike,
            right=right,
            exchange=exchange,
            underlying_conid=underlying_conid,
            conid=conid,
        )
        snapshot_rows = await self.adapter.get_snapshot(
            [contract.conid],
            fields=(
                "31",
                "84",
                "86",
                "201",
                "6070",
                "6457",
                "6509",
                "7089",
                "7283",
                "7308",
                "7309",
                "7310",
                "7311",
                "7633",
                "7635",
                "7638",
            ),
        )
        snapshot = snapshot_rows[0] if snapshot_rows else {}
        snapshot_underlying_conid = _snapshot_text(snapshot, "6457")
        resolved_underlying_conid = (
            snapshot_underlying_conid or contract.underlying_conid or underlying_conid
        )
        underlying_last_price = None
        if resolved_underlying_conid:
            underlying_snapshot_rows = await self.adapter.get_snapshot(
                [resolved_underlying_conid],
                fields=("31",),
            )
            if underlying_snapshot_rows:
                underlying_last_price = _snapshot_float(underlying_snapshot_rows[0], "31")

        availability = _snapshot_text(snapshot, "6509")
        return {
            "symbol": symbol.upper(),
            "conid": contract.conid,
            "exchange": contract.exchange,
            "asset_class": contract.asset_class,
            "currency": contract.currency,
            "expiry": contract.expiry or expiry,
            "strike": contract.strike if contract.strike is not None else strike,
            "right": contract.right or (right.upper() if right else None),
            "multiplier": _contract_multiplier(contract),
            "underlying_conid": resolved_underlying_conid,
            "last_price": _snapshot_float(snapshot, "31"),
            "bid": _snapshot_float(snapshot, "84"),
            "ask": _snapshot_float(snapshot, "86"),
            "mark": _snapshot_float(snapshot, "7635"),
            "delta": _snapshot_float(snapshot, "7308"),
            "gamma": _snapshot_float(snapshot, "7309"),
            "theta": _snapshot_float(snapshot, "7310"),
            "vega": _snapshot_float(snapshot, "7311"),
            "implied_vol_pct": _snapshot_float(snapshot, "7633"),
            "underlying_implied_vol_pct": _snapshot_float(snapshot, "7283"),
            "open_interest": _snapshot_float(snapshot, "7638"),
            "option_volume": _snapshot_float(snapshot, "7089"),
            "underlying_last_price": underlying_last_price,
            "market_data_availability": availability,
            "data_is_delayed": availability.startswith(("D", "Y")) if availability else None,
            "raw": snapshot,
        }

    async def _resolve_option_contract(
        self,
        symbol: str,
        *,
        expiry: str | None,
        strike: float | None,
        right: str | None,
        exchange: str | None,
        underlying_conid: str | None,
        conid: str | None,
    ) -> IBKRContract:
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
            field_name
            for field_name, value in (("expiry", expiry), ("strike", strike), ("right", right))
            if value is None
        ]
        if missing:
            raise ValueError(
                "Option greeks require expiry, strike, and right unless an explicit "
                "option conid is supplied."
            )
        normalized_right = str(right).upper()
        if normalized_right not in {"C", "P"}:
            raise ValueError("Option right must be 'C' or 'P'.")
        return await self.adapter.resolve_option_contract(
            symbol,
            expiry=str(expiry),
            strike=float(strike),
            right=normalized_right,
            exchange=exchange,
            underlying_conid=underlying_conid,
            conid=conid,
        )


def _bar_dict(b: BarData) -> dict[str, Any]:
    return {
        "timestamp": b.timestamp.isoformat(),
        "open": b.open,
        "high": b.high,
        "low": b.low,
        "close": b.close,
        "volume": b.volume,
        "vwap": b.vwap,
    }


def _contract_dict(c: IBKRContract) -> dict[str, Any]:
    return {
        "conid": c.conid,
        "symbol": c.symbol,
        "exchange": c.exchange,
        "asset_class": c.asset_class,
        "description": c.description,
        "currency": c.currency,
        "expiry": c.expiry or None,
        "strike": c.strike,
        "right": c.right or None,
        "multiplier": c.multiplier or None,
        "trading_class": c.trading_class or None,
        "underlying_conid": c.underlying_conid or None,
        "option_months": list(c.option_months),
        "option_exchanges": list(c.option_exchanges),
        "valid_exchanges": list(c.valid_exchanges),
    }


def _contract_multiplier(contract: IBKRContract) -> float:
    if contract.multiplier:
        try:
            value = float(contract.multiplier)
        except (TypeError, ValueError):
            value = 0.0
        if value > 0:
            return value
    return 100.0 if contract.asset_class.upper() == "OPT" else 1.0


async def _last_price_or_none(adapter: IBKRMarketDataAdapter, conid: str) -> float | None:
    quotes = await adapter.get_quotes([conid])
    if not quotes:
        return None
    price = safe_float(quotes[0].get("31"), 0.0)
    return round(price, 4) if price > 0 else None


def _snapshot_text(snapshot: dict[str, Any], field: str) -> str:
    value = snapshot.get(field)
    if value is None:
        return ""
    return str(value).strip()


def _snapshot_float(snapshot: dict[str, Any], field: str) -> float | None:
    value = snapshot.get(field)
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).replace(",", "").replace("%", "").strip()
    if not text:
        return None
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def _normalize_chain_expiry(expiry: str) -> str:
    expiry_text = expiry.strip().upper()
    if len(expiry_text) == 5 and expiry_text[:3].isalpha() and expiry_text[3:].isdigit():
        return expiry_text
    normalized = expiry_text.replace("-", "")
    if len(normalized) == 8 and normalized.isdigit():
        return datetime(int(normalized[:4]), int(normalized[4:6]), 1).strftime("%b%y").upper()
    raise ValueError("expiry must be YYYY-MM-DD, YYYYMMDD, or IBKR month format like JAN25")


def _select_strikes(
    strikes: list[float],
    *,
    center: float | None,
    min_strike: float | None,
    max_strike: float | None,
    strike_limit: int,
) -> list[float]:
    filtered = [
        strike
        for strike in sorted(set(strikes))
        if (min_strike is None or strike >= min_strike)
        and (max_strike is None or strike <= max_strike)
    ]
    if strike_limit <= 0 or len(filtered) <= strike_limit:
        return filtered
    if center is None:
        return filtered[:strike_limit]

    closest_index = min(range(len(filtered)), key=lambda idx: abs(filtered[idx] - center))
    half_window = strike_limit // 2
    start = max(closest_index - half_window, 0)
    end = min(start + strike_limit, len(filtered))
    start = max(end - strike_limit, 0)
    return filtered[start:end]
