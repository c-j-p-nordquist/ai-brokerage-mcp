from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

from agentic_brokerage_mcp.ibkr.client import IBKRClient
from agentic_brokerage_mcp.ibkr.session import IBKRSessionManager
from agentic_brokerage_mcp.models import BarData, IBKRContract

logger = logging.getLogger("agentic_brokerage_mcp.ibkr.market_data")


class AmbiguousContractError(RuntimeError):
    def __init__(self, symbol: str, candidates: list[IBKRContract]):
        self.symbol = symbol.upper()
        self.candidates = candidates
        formatted = ", ".join(_candidate_label(candidate) for candidate in candidates[:5])
        more = " ..." if len(candidates) > 5 else ""
        message = (
            f"Ambiguous IBKR contract for symbol '{self.symbol}'. "
            f"Pass conid=. Candidates: {formatted}{more}"
        )
        super().__init__(message)


class IBKRMarketDataAdapter:
    def __init__(self, client: IBKRClient, session: IBKRSessionManager):
        self.client = client
        self.session = session
        self._conid_cache: dict[str, IBKRContract] = {}

    async def search_contracts(
        self,
        query: str,
        sec_type: str | None = "STK",
        *,
        name: bool | None = True,
    ) -> list[IBKRContract]:
        await self.session.ensure_session()
        params: dict[str, Any] = {"symbol": query}
        if name is not None:
            params["name"] = name
        if sec_type:
            params["secType"] = sec_type
        payload = await self.client.request(
            "GET",
            "/iserver/secdef/search",
            params=params,
        )
        if not isinstance(payload, list):
            return []
        results = []
        for item in payload:
            if not isinstance(item, dict) or not item.get("conid"):
                continue
            results.append(
                self._contract_from_search_result(
                    item,
                    default_symbol=query,
                    default_sec_type=sec_type or str(item.get("secType", "")),
                )
            )
        return results

    async def resolve_contract(
        self,
        symbol: str,
        sec_type: str = "STK",
        *,
        conid: str | None = None,
    ) -> IBKRContract:
        cache_key = f"{symbol.upper()}:{sec_type}:{conid or ''}"
        if cache_key in self._conid_cache:
            return self._conid_cache[cache_key]

        contracts = await self.search_contracts(symbol, sec_type)
        if not contracts and conid is not None:
            contract = await self._hydrate_contract(
                IBKRContract(
                    conid=str(conid),
                    symbol=symbol.upper(),
                    exchange="",
                    asset_class=sec_type,
                )
            )
            self._conid_cache[cache_key] = contract
            return contract
        if not contracts:
            raise RuntimeError(f"No IBKR contract found for {symbol}")

        if conid is not None:
            for contract in contracts:
                if contract.conid == str(conid):
                    contract = await self._hydrate_contract(contract)
                    self._conid_cache[cache_key] = contract
                    return contract
            contract = await self._hydrate_contract(
                IBKRContract(
                    conid=str(conid),
                    symbol=symbol.upper(),
                    exchange="",
                    asset_class=sec_type,
                )
            )
            self._conid_cache[cache_key] = contract
            return contract

        exact_symbol_matches = [
            contract for contract in contracts if contract.symbol.upper() == symbol.upper()
        ]
        candidates = exact_symbol_matches or contracts
        if len(candidates) > 1:
            picked = _pick_primary_us_listing(candidates)
            if picked is None:
                hydrated = [await self._hydrate_contract(c) for c in candidates]
                picked = _pick_primary_us_listing(hydrated)
                if picked is None:
                    picked = _pick_single_usd(hydrated)
                if picked is not None:
                    candidates = hydrated
            if picked is None:
                raise AmbiguousContractError(symbol, candidates)
            logger.warning(
                "ibkr_contract_auto_disambiguated symbol=%s picked_conid=%s candidates=%s",
                symbol.upper(),
                picked.conid,
                ",".join(c.conid for c in candidates),
            )
            candidates = [picked]

        contract = await self._hydrate_contract(candidates[0])
        self._conid_cache[cache_key] = contract
        return contract

    async def resolve_option_underlying(
        self,
        symbol: str,
        *,
        underlying_conid: str | None = None,
    ) -> IBKRContract:
        contracts = await self.search_contracts(symbol, sec_type=None, name=None)
        candidates = [c for c in contracts if c.option_months]
        if not candidates:
            raise RuntimeError(f"No option-enabled IBKR contract found for {symbol}")

        if underlying_conid is not None:
            for contract in candidates:
                if contract.conid == str(underlying_conid):
                    return contract
            raise RuntimeError(
                f"Underlying conid {underlying_conid} was not found for option "
                f"symbol {symbol.upper()}"
            )

        exact_symbol_matches = [
            contract for contract in candidates if contract.symbol.upper() == symbol.upper()
        ]
        selected = exact_symbol_matches or candidates
        if len(selected) > 1:
            raise AmbiguousContractError(symbol, selected)
        return selected[0]

    async def get_option_strikes(
        self,
        *,
        underlying_conid: str,
        month: str,
        exchange: str | None = None,
        sec_type: str = "OPT",
    ) -> dict[str, list[float]]:
        await self.session.ensure_session()
        params: dict[str, Any] = {
            "conid": underlying_conid,
            "secType": sec_type,
            "month": month,
        }
        if exchange:
            params["exchange"] = exchange
        payload = await self.client.request("GET", "/iserver/secdef/strikes", params=params)
        if not isinstance(payload, dict):
            return {"call": [], "put": []}
        return {
            "call": _float_list(payload.get("call")),
            "put": _float_list(payload.get("put")),
        }

    async def get_option_contracts(
        self,
        *,
        underlying_conid: str,
        month: str,
        strike: float,
        right: str,
        exchange: str | None = None,
        sec_type: str = "OPT",
    ) -> list[IBKRContract]:
        await self.session.ensure_session()
        params: dict[str, Any] = {
            "conid": underlying_conid,
            "secType": sec_type,
            "month": month,
            "strike": strike,
            "right": right.upper(),
        }
        if exchange:
            params["exchange"] = exchange
        payload = await self.client.request("GET", "/iserver/secdef/info", params=params)
        if not isinstance(payload, list):
            return []
        return [
            self._contract_from_info_result(item)
            for item in payload
            if isinstance(item, dict) and item.get("conid")
        ]

    async def search_option_contracts(
        self,
        symbol: str,
        *,
        expiry: str,
        strike: float,
        right: str,
        exchange: str | None = None,
        underlying_conid: str | None = None,
        sec_type: str = "OPT",
    ) -> list[IBKRContract]:
        underlying = await self.resolve_option_underlying(symbol, underlying_conid=underlying_conid)
        normalized_right = right.upper()
        if normalized_right not in {"C", "P"}:
            raise ValueError("Option right must be 'C' or 'P'.")
        month, exact_expiry = _normalize_option_expiry(expiry)
        strikes = await self.get_option_strikes(
            underlying_conid=underlying.conid,
            month=month,
            exchange=exchange,
            sec_type=sec_type,
        )
        strike_side = "call" if normalized_right == "C" else "put"
        available_strikes = strikes.get(strike_side, [])
        if available_strikes and not any(
            _same_strike(candidate, strike) for candidate in available_strikes
        ):
            return []

        contracts = await self.get_option_contracts(
            underlying_conid=underlying.conid,
            month=month,
            strike=strike,
            right=normalized_right,
            exchange=exchange,
            sec_type=sec_type,
        )
        if exact_expiry:
            contracts = [contract for contract in contracts if contract.expiry == exact_expiry]
        return contracts

    async def resolve_option_contract(
        self,
        symbol: str,
        *,
        expiry: str,
        strike: float,
        right: str,
        exchange: str | None = None,
        underlying_conid: str | None = None,
        conid: str | None = None,
        sec_type: str = "OPT",
    ) -> IBKRContract:
        contracts = await self.search_option_contracts(
            symbol,
            expiry=expiry,
            strike=strike,
            right=right,
            exchange=exchange,
            underlying_conid=underlying_conid,
            sec_type=sec_type,
        )
        if conid is not None:
            for contract in contracts:
                if contract.conid == str(conid):
                    return contract
            raise RuntimeError(
                f"Option conid {conid} did not match {symbol} {expiry} {strike} {right}"
            )

        if not contracts:
            raise RuntimeError(
                f"No IBKR option contract found for {symbol} {expiry} {strike} {right}"
            )
        if len(contracts) > 1:
            raise AmbiguousContractError(symbol, contracts)
        return contracts[0]

    async def get_quotes(self, conids: list[str]) -> list[dict[str, Any]]:
        return await self.get_snapshot(conids, fields=("31", "84", "86"))

    async def get_snapshot(
        self,
        conids: list[str],
        *,
        fields: list[str] | tuple[str, ...],
    ) -> list[dict[str, Any]]:
        await self.session.ensure_session()
        conids_str = ",".join(conids)
        normalized_fields = _normalize_snapshot_fields(fields)
        fields_str = ",".join(normalized_fields)
        payload = await self.client.request(
            "GET",
            "/iserver/marketdata/snapshot",
            params={"conids": conids_str, "fields": fields_str},
        )
        rows = payload if isinstance(payload, list) else []
        if rows and _rows_have_requested_snapshot_fields(rows, normalized_fields):
            return rows

        if not rows or not _rows_have_requested_snapshot_fields(rows, normalized_fields):
            await asyncio.sleep(0)
            retry_payload = await self.client.request(
                "GET",
                "/iserver/marketdata/snapshot",
                params={"conids": conids_str, "fields": fields_str},
            )
            retry_rows = retry_payload if isinstance(retry_payload, list) else []
            if retry_rows:
                return retry_rows

        return rows

    async def get_historical_bars(
        self,
        *,
        conid: str,
        period: str = "1M",
        bar: str = "1d",
        outside_rth: bool = False,
    ) -> list[BarData]:
        await self.session.ensure_session()
        params: dict[str, Any] = {
            "conid": conid,
            "period": period,
            "bar": bar,
            "outsideRth": outside_rth,
        }
        payload = await self.client.request("GET", "/iserver/marketdata/history", params=params)
        data = payload.get("data", []) if isinstance(payload, dict) else []
        return [self._to_bar(item) for item in data if isinstance(item, dict)]

    async def get_news_headlines(self, conid: str, *, count: int = 20) -> list[dict[str, Any]]:
        await self.session.ensure_session()
        payload = await self.client.request(
            "GET",
            "/iserver/news/briefing",
            params={"conid": conid, "count": count},
        )
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict):
            return payload.get("articles", payload.get("data", []))
        return []

    async def get_news_article(self, article_id: str) -> dict[str, Any]:
        await self.session.ensure_session()
        payload = await self.client.request(
            "GET", "/iserver/news/article", params={"id": article_id}
        )
        return payload if isinstance(payload, dict) else {"text": str(payload)}

    async def get_contract_info(self, conid: str) -> dict[str, Any]:
        await self.session.ensure_session()
        payload = await self.client.request("GET", f"/iserver/contract/{conid}/info")
        if isinstance(payload, dict) and payload:
            return payload

        payload = await self.client.request("GET", "/trsrv/secdef", params={"conids": str(conid)})
        if isinstance(payload, dict):
            secdef_rows = payload.get("secdef")
            if isinstance(secdef_rows, list):
                for row in secdef_rows:
                    if isinstance(row, dict) and str(row.get("conid")) == str(conid):
                        return row
        return {}

    async def _hydrate_contract(self, contract: IBKRContract) -> IBKRContract:
        if contract.currency and contract.exchange and contract.description:
            return contract

        try:
            info = await self.get_contract_info(contract.conid)
        except Exception:
            return contract
        if not info:
            return contract

        return IBKRContract(
            conid=contract.conid,
            symbol=str(info.get("symbol") or info.get("ticker") or contract.symbol),
            exchange=str(
                info.get("exchange") or info.get("listingExchange") or contract.exchange or "SMART"
            ),
            asset_class=str(
                info.get("instrument_type")
                or info.get("assetClass")
                or info.get("secType")
                or contract.asset_class
            ),
            description=str(
                info.get("company_name")
                or info.get("name")
                or info.get("description")
                or contract.description
            ),
            currency=str(info.get("currency") or contract.currency),
            expiry=str(
                info.get("expiry_full")
                or info.get("lastTradingDay")
                or info.get("expiry")
                or contract.expiry
            ),
            strike=_float_or_none(info.get("strike"))
            if info.get("strike") is not None
            else contract.strike,
            right=str(info.get("putOrCall") or info.get("right") or contract.right),
            multiplier=_clean_multiplier(info.get("multiplier")) or contract.multiplier,
            trading_class=str(
                info.get("trading_class") or info.get("tradingClass") or contract.trading_class
            ),
            underlying_conid=str(
                info.get("underlying_con_id") or info.get("undConid") or contract.underlying_conid
            ),
            option_months=contract.option_months,
            option_exchanges=contract.option_exchanges,
            valid_exchanges=_split_semicolon_values(
                info.get("valid_exchanges")
                or info.get("allExchanges")
                or info.get("validExchanges")
            )
            or contract.valid_exchanges,
        )

    @staticmethod
    def _to_bar(item: dict[str, Any]) -> BarData:
        epoch_ms = int(item.get("t", 0))
        return BarData(
            timestamp=datetime.fromtimestamp(epoch_ms / 1000, tz=UTC),
            open=float(item.get("o", 0)),
            high=float(item.get("h", 0)),
            low=float(item.get("l", 0)),
            close=float(item.get("c", 0)),
            volume=float(item.get("v", 0)),
            vwap=float(item["vw"]) if item.get("vw") is not None else None,
        )

    @staticmethod
    def _contract_from_search_result(
        item: dict[str, Any],
        *,
        default_symbol: str,
        default_sec_type: str,
    ) -> IBKRContract:
        option_section = _option_section(item)
        return IBKRContract(
            conid=str(item["conid"]),
            symbol=str(item.get("symbol", default_symbol)),
            exchange=str(item.get("listingExchange") or item.get("description") or "SMART"),
            asset_class=str(item.get("secType", default_sec_type)),
            description=str(item.get("description") or item.get("companyName") or ""),
            currency=str(item.get("currency", "")),
            expiry=str(item.get("expiry") or item.get("lastTradingDay") or ""),
            strike=_float_or_none(item.get("strike")),
            right=str(item.get("putOrCall") or item.get("right") or ""),
            multiplier=_clean_multiplier(item.get("multiplier")),
            trading_class=str(item.get("tradingClass") or ""),
            underlying_conid=str(item.get("undConid") or ""),
            option_months=_split_semicolon_values(
                option_section.get("months") if option_section else None
            ),
            option_exchanges=_split_semicolon_values(
                option_section.get("exchange") if option_section else None
            ),
            valid_exchanges=_split_semicolon_values(item.get("validExchanges")),
        )

    @staticmethod
    def _contract_from_info_result(item: dict[str, Any]) -> IBKRContract:
        return IBKRContract(
            conid=str(item["conid"]),
            symbol=str(item.get("symbol", "")),
            exchange=str(item.get("exchange") or item.get("listingExchange") or "SMART"),
            asset_class=str(item.get("secType", "")),
            description=str(item.get("desc2") or item.get("desc1") or ""),
            currency=str(item.get("currency", "")),
            expiry=str(item.get("maturityDate") or item.get("lastTradingDay") or ""),
            strike=_float_or_none(item.get("strike")),
            right=str(item.get("right") or ""),
            multiplier=_clean_multiplier(item.get("multiplier")),
            trading_class=str(item.get("tradingClass") or ""),
            underlying_conid=str(item.get("undConid") or ""),
            valid_exchanges=_split_semicolon_values(item.get("validExchanges")),
        )


_PRIMARY_US_EXCHANGES = frozenset(
    {"NASDAQ", "NYSE", "ARCA", "AMEX", "BATS", "IEX", "NYSEMKT", "NMS"}
)


def _pick_single_usd(candidates: list[IBKRContract]) -> IBKRContract | None:
    usd = [c for c in candidates if (c.currency or "").upper() == "USD"]
    if len(usd) != 1:
        return None
    return usd[0]


def _pick_primary_us_listing(candidates: list[IBKRContract]) -> IBKRContract | None:
    def is_primary(contract: IBKRContract) -> bool:
        listing = (contract.exchange or "").upper()
        if listing in _PRIMARY_US_EXCHANGES:
            return True
        valid = {ex.upper() for ex in contract.valid_exchanges}
        return bool(valid & _PRIMARY_US_EXCHANGES)

    primary = [c for c in candidates if is_primary(c)]
    if len(primary) != 1:
        return None
    return primary[0]


def _candidate_label(contract: IBKRContract) -> str:
    details = [contract.symbol.upper(), contract.conid]
    if contract.exchange:
        details.append(contract.exchange)
    if contract.expiry:
        details.append(contract.expiry)
    if contract.right:
        details.append(contract.right.upper())
    if contract.strike is not None:
        details.append(str(contract.strike))
    if contract.currency:
        details.append(contract.currency)
    return "/".join(details)


def _option_section(item: dict[str, Any], sec_type: str = "OPT") -> dict[str, Any] | None:
    sections = item.get("sections")
    if not isinstance(sections, list):
        return None
    for section in sections:
        if not isinstance(section, dict):
            continue
        if str(section.get("secType", "")).upper() == sec_type.upper():
            return section
    return None


def _split_semicolon_values(value: Any) -> tuple[str, ...]:
    if not isinstance(value, str) or not value:
        return ()
    return tuple(part for part in (piece.strip() for piece in value.split(";")) if part)


def _float_or_none(value: Any) -> float | None:
    if value in (None, "", "0", 0):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _clean_multiplier(value: Any) -> str:
    if value in (None, "", 0, 0.0, "0", "0.0"):
        return ""
    return str(value)


def _float_list(value: Any) -> list[float]:
    if not isinstance(value, list):
        return []
    items: list[float] = []
    for raw in value:
        parsed = _float_or_none(raw)
        if parsed is not None:
            items.append(parsed)
    return sorted(set(items))


def _normalize_option_expiry(expiry: str) -> tuple[str, str | None]:
    expiry_text = expiry.strip().upper()
    if len(expiry_text) == 5 and expiry_text[:3].isalpha() and expiry_text[3:].isdigit():
        return expiry_text, None

    normalized = expiry_text.replace("-", "")
    if len(normalized) == 8 and normalized.isdigit():
        year = int(normalized[:4])
        month = int(normalized[4:6])
        month_code = datetime(year, month, 1, tzinfo=UTC).strftime("%b%y").upper()
        return month_code, normalized

    raise ValueError("expiry must be YYYY-MM-DD, YYYYMMDD, or IBKR month format like JAN25")


def _same_strike(left: float, right: float) -> bool:
    return abs(left - right) < 1e-9


def _normalize_snapshot_fields(fields: list[str] | tuple[str, ...]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for raw in fields:
        field = str(raw).strip()
        if not field or field in seen:
            continue
        seen.add(field)
        normalized.append(field)
    if not normalized:
        raise ValueError("At least one market data field must be requested")
    return normalized


def _rows_have_requested_snapshot_fields(
    rows: list[dict[str, Any]],
    requested_fields: list[str],
) -> bool:
    requested = set(requested_fields)
    if not requested:
        return True
    for row in rows:
        if not isinstance(row, dict):
            continue
        if requested.intersection(row.keys()):
            return True
    return False
