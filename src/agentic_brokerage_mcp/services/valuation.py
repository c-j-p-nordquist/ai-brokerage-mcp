from __future__ import annotations

import re
from typing import Any

from agentic_brokerage_mcp.config import settings

BASE_CURRENCY = settings.base_currency


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        if not isinstance(value, str):
            return default
        text = value.replace(",", "").replace("%", "").strip()
        if not text:
            return default
        negative = text.startswith("(") and text.endswith(")")
        match = re.search(r"[-+]?\d+(?:\.\d+)?", text)
        if not match:
            return default
        try:
            result = float(match.group(0))
        except ValueError:
            return default
        if negative:
            result = -result
    if result != result:  # NaN
        return default
    return result


def estimate_currency_rates(
    summary: dict[str, Any],
    ledger: dict[str, Any] | None,
    positions: list[dict[str, Any]],
    *,
    base_currency: str = BASE_CURRENCY,
) -> tuple[dict[str, dict[str, Any]], list[str]]:
    rates: dict[str, dict[str, Any]] = {
        base_currency: {"rate": 1.0, "source": "base_currency"},
    }
    notes: list[str] = []

    if isinstance(ledger, dict):
        for currency, payload in ledger.items():
            code = str(currency).upper()
            if len(code) != 3 or not code.isalpha() or not isinstance(payload, dict):
                continue
            rate = _extract_currency_rate(payload)
            if rate > 0:
                rates[code] = {"rate": rate, "source": "ledger"}

    foreign_totals: dict[str, float] = {}
    base_currency_total = 0.0
    for position in positions:
        currency = str(position.get("currency") or base_currency).upper()
        native_market_value = abs(
            safe_float(position.get("market_value", position.get("mktValue")))
        )
        if native_market_value <= 0:
            continue
        if currency == base_currency:
            base_currency_total += native_market_value
            continue
        foreign_totals[currency] = foreign_totals.get(currency, 0.0) + native_market_value

    gross_position_value_base = safe_float(summary.get("gross_position_value"))
    foreign_value_budget_base = max(gross_position_value_base - base_currency_total, 0.0)

    known_foreign_base = 0.0
    unknown_currencies: list[str] = []
    for currency, native_total in foreign_totals.items():
        if currency in rates:
            known_foreign_base += native_total * safe_float(rates[currency]["rate"], 1.0)
        else:
            unknown_currencies.append(currency)

    if unknown_currencies:
        remaining_base = max(foreign_value_budget_base - known_foreign_base, 0.0)
        unknown_native_total = sum(foreign_totals[c] for c in unknown_currencies)
        if len(unknown_currencies) == 1 and unknown_native_total > 0 and remaining_base > 0:
            currency = unknown_currencies[0]
            rates[currency] = {
                "rate": remaining_base / foreign_totals[currency],
                "source": "portfolio_implied",
            }
        elif unknown_native_total > 0 and foreign_value_budget_base > 0:
            blended_rate = foreign_value_budget_base / max(sum(foreign_totals.values()), 1e-9)
            for currency in unknown_currencies:
                rates[currency] = {
                    "rate": blended_rate,
                    "source": "blended_portfolio_implied",
                }
            notes.append("Some non-base currency values use a blended portfolio-implied FX rate.")

    for currency in foreign_totals:
        if currency in rates:
            continue
        rates[currency] = {"rate": 1.0, "source": "assumed_1.0"}
        notes.append(f"Missing FX conversion for {currency}; assuming 1.0 to {base_currency}.")

    return rates, notes


def convert_native_to_base(
    amount: float,
    currency: str | None,
    rates: dict[str, dict[str, Any]],
    *,
    base_currency: str = BASE_CURRENCY,
) -> tuple[float, float, str]:
    code = str(currency or base_currency).upper()
    if code == base_currency:
        return amount, 1.0, "base_currency"

    rate_info = rates.get(code, {"rate": 1.0, "source": "assumed_1.0"})
    rate = safe_float(rate_info.get("rate"), 1.0)
    return amount * rate, rate, str(rate_info.get("source", "assumed_1.0"))


def summarize_fx_sources(
    rates: dict[str, dict[str, Any]],
    *,
    base_currency: str = BASE_CURRENCY,
) -> list[dict[str, Any]]:
    rows = []
    for currency, rate_info in sorted(rates.items()):
        rows.append(
            {
                "currency": currency,
                "base_currency": base_currency,
                "rate_to_base": round(safe_float(rate_info.get("rate"), 1.0), 6),
                "source": str(rate_info.get("source", "")),
            }
        )
    return rows


def _extract_currency_rate(payload: dict[str, Any]) -> float:
    direct_keys = (
        "exchangeRate",
        "exchange_rate",
        "fxRate",
        "fx_rate",
        "rate",
    )
    for key in direct_keys:
        rate = safe_float(payload.get(key), 0.0)
        if rate > 0:
            return rate

    nested_keys = (
        "toBase",
        "to_base",
        "baseRate",
        "base_rate",
    )
    for key in nested_keys:
        value = payload.get(key)
        if not isinstance(value, dict):
            continue
        rate = safe_float(value.get("rate"), 0.0)
        if rate > 0:
            return rate

    return 0.0
