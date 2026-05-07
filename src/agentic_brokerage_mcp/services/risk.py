from __future__ import annotations

from typing import Any

import pandas as pd
from ta.volatility import AverageTrueRange

from agentic_brokerage_mcp.ibkr.account import IBKRAccountAdapter
from agentic_brokerage_mcp.ibkr.market_data import IBKRMarketDataAdapter
from agentic_brokerage_mcp.ibkr.orders import IBKROrderAdapter
from agentic_brokerage_mcp.services.valuation import BASE_CURRENCY


class RiskService:
    def __init__(
        self,
        market_data: IBKRMarketDataAdapter,
        account_adapter: IBKRAccountAdapter,
        order_adapter: IBKROrderAdapter,
        account_id: str,
    ):
        self.market_data = market_data
        self.account_adapter = account_adapter
        self.order_adapter = order_adapter
        self.account_id = account_id

    async def position_size(
        self,
        symbol: str,
        *,
        risk_pct: float = 1.0,
        stop_distance: float | None = None,
        conid: str | None = None,
    ) -> dict[str, Any]:
        summary = await self.account_adapter.account_summary(self.account_id)
        nlv = float(summary.get("net_liquidation", 0) or 0)
        risk_amount = nlv * (risk_pct / 100)

        contract = await self.market_data.resolve_contract(symbol, conid=conid)
        bars: list[Any] = []

        if stop_distance is None:
            bars = await self.market_data.get_historical_bars(
                conid=contract.conid, period="1M", bar="1d"
            )
            if bars:
                df = pd.DataFrame([{"high": b.high, "low": b.low, "close": b.close} for b in bars])
                atr = AverageTrueRange(df["high"], df["low"], df["close"], window=14)
                atr_val = atr.average_true_range().dropna()
                stop_distance = float(atr_val.iloc[-1]) * 1.5 if not atr_val.empty else None

        if stop_distance and stop_distance > 0:
            shares = int(risk_amount / stop_distance)
        else:
            shares = 0

        last_price = await self._resolve_last_price(contract.conid, bars=bars)
        total_cost = shares * last_price if last_price else 0

        return {
            "symbol": symbol.upper(),
            "conid": contract.conid,
            "account_value": nlv,
            "risk_pct": risk_pct,
            "risk_amount": round(risk_amount, 2),
            "stop_distance": round(stop_distance, 4) if stop_distance else None,
            "suggested_shares": shares,
            "estimated_cost": round(total_cost, 2),
            "last_price": last_price,
        }

    async def portfolio_aware_position_size(
        self,
        symbol: str,
        *,
        risk_pct: float = 1.0,
        stop_distance: float | None = None,
        conid: str | None = None,
    ) -> dict[str, Any]:
        summary = await self.account_adapter.account_summary(self.account_id)
        nlv = float(summary.get("net_liquidation", 0) or 0)
        cash = float(summary.get("total_cash", 0) or 0)
        available_funds = float(summary.get("available_funds", cash) or 0)
        excess_liquidity = float(summary.get("excess_liquidity", cash) or 0)
        risk_amount_base = nlv * (risk_pct / 100)

        contract = await self.market_data.resolve_contract(symbol, conid=conid)
        stop_distance, last_price, _bars = await self._position_inputs(
            contract.conid, stop_distance=stop_distance
        )

        positions = self._normalize_positions(
            await self.order_adapter.portfolio_positions(self.account_id)
        )
        live_orders_payload = await self.order_adapter.live_orders()
        live_orders = self._normalize_live_orders(live_orders_payload)

        fx_rate, fx_rate_source = self._estimate_base_to_quote_rate(
            summary,
            positions,
            quote_currency=contract.currency,
        )
        margin_profile = self._estimate_margin_profile(summary)

        risk_amount_quote = risk_amount_base / fx_rate if fx_rate > 0 else 0.0
        baseline_shares = (
            int(risk_amount_quote / stop_distance)
            if stop_distance and stop_distance > 0 and risk_amount_quote > 0
            else 0
        )

        symbol_upper = symbol.upper()
        current_position = next((p for p in positions if p["symbol"] == symbol_upper), None)
        current_shares = float(current_position["position"]) if current_position else 0.0
        pending_buy_shares, pending_sell_shares = self._pending_shares_for_symbol(
            symbol_upper, contract.conid, live_orders
        )
        effective_current_shares = current_shares + pending_buy_shares - pending_sell_shares

        baseline_cost_quote = baseline_shares * last_price if last_price > 0 else 0.0
        baseline_cost_base = baseline_cost_quote * fx_rate

        observations = []

        if fx_rate_source == "assumed_1.0":
            observations.append(
                "Could not infer an FX rate from current holdings; assuming account "
                "base and quote currencies match."
            )

        if stop_distance is None or stop_distance <= 0:
            observations.append(
                "No positive stop distance available for the baseline size calculation."
            )
        if last_price <= 0:
            observations.append("No last price available for the portfolio context calculation.")

        per_share_value_base = last_price * fx_rate if last_price > 0 and fx_rate > 0 else 0.0
        current_position_value_base = 0.0
        if current_position:
            current_position_value_native = float(current_position["market_value"])
            if current_position_value_native > 0 and fx_rate > 0:
                current_position_value_base = current_position_value_native * fx_rate
            else:
                current_position_value_base = max(current_shares, 0.0) * per_share_value_base
        current_position_value_base += (
            pending_buy_shares - pending_sell_shares
        ) * per_share_value_base

        estimated_initial_margin_used = baseline_cost_base * margin_profile["initial_margin_ratio"]
        estimated_maintenance_margin_used = (
            baseline_cost_base * margin_profile["maintenance_margin_ratio"]
        )
        post_trade_position_value_base = current_position_value_base + baseline_cost_base
        post_trade_position_pct = (
            post_trade_position_value_base / nlv * 100
            if nlv and post_trade_position_value_base
            else 0.0
        )
        current_position_pct = (
            current_position_value_base / nlv * 100 if nlv and current_position_value_base else 0.0
        )
        post_trade_cash_base = cash - baseline_cost_base
        post_trade_cash_pct = post_trade_cash_base / nlv * 100 if nlv else 0.0
        post_trade_available_funds = available_funds - estimated_initial_margin_used
        post_trade_available_funds_pct = post_trade_available_funds / nlv * 100 if nlv else 0.0
        post_trade_excess_liquidity = excess_liquidity - estimated_maintenance_margin_used
        post_trade_excess_liquidity_pct = post_trade_excess_liquidity / nlv * 100 if nlv else 0.0
        estimated_open_risk_added_base = (
            baseline_shares * stop_distance * fx_rate
            if baseline_shares > 0 and stop_distance and fx_rate > 0
            else 0.0
        )

        if pending_buy_shares or pending_sell_shares:
            observations.append(
                f"Live orders already affect {symbol_upper} exposure: "
                f"+{pending_buy_shares:g} buy shares, "
                f"-{pending_sell_shares:g} sell shares."
            )
        if current_position_pct >= 25:
            observations.append(
                f"Current {symbol_upper} exposure is {current_position_pct:.2f}% of account value."
            )
        if post_trade_position_pct >= 25:
            observations.append(
                f"The baseline size would bring {symbol_upper} exposure to "
                f"{post_trade_position_pct:.2f}% of account value."
            )
        if post_trade_cash_base < 0:
            observations.append(
                "The baseline size would take cash below zero and rely on margin financing."
            )
        if post_trade_available_funds < 0:
            observations.append(
                "Estimated initial margin for the baseline size exceeds current available funds."
            )
        if post_trade_excess_liquidity < 0:
            observations.append(
                "Estimated maintenance margin for the baseline size exceeds current "
                "excess liquidity."
            )
        if margin_profile["source"] != "portfolio_implied":
            observations.append(
                "Margin limits use fallback ratios because the portfolio summary did "
                "not provide enough data to infer them."
            )

        return {
            "symbol": symbol_upper,
            "conid": contract.conid,
            "account_value": nlv,
            "account_cash": round(cash, 2),
            "available_funds": round(available_funds, 2),
            "excess_liquidity": round(excess_liquidity, 2),
            "risk_pct": risk_pct,
            "risk_amount_base": round(risk_amount_base, 2),
            "base_to_quote_rate": round(fx_rate, 4),
            "base_to_quote_rate_source": fx_rate_source,
            "estimated_initial_margin_ratio": round(margin_profile["initial_margin_ratio"], 4),
            "estimated_maintenance_margin_ratio": round(
                margin_profile["maintenance_margin_ratio"], 4
            ),
            "margin_ratio_source": margin_profile["source"],
            "stop_distance": round(stop_distance, 4) if stop_distance else None,
            "last_price": last_price,
            "baseline_shares": baseline_shares,
            "baseline_estimated_cost": round(baseline_cost_quote, 2),
            "baseline_estimated_cost_base": round(baseline_cost_base, 2),
            "current_position_shares": current_shares,
            "pending_buy_shares": pending_buy_shares,
            "pending_sell_shares": pending_sell_shares,
            "effective_current_shares": effective_current_shares,
            "current_position_pct": round(current_position_pct, 2),
            "post_trade_available_funds": round(post_trade_available_funds, 2),
            "post_trade_available_funds_pct": round(post_trade_available_funds_pct, 2),
            "post_trade_excess_liquidity": round(post_trade_excess_liquidity, 2),
            "post_trade_excess_liquidity_pct": round(post_trade_excess_liquidity_pct, 2),
            "estimated_initial_margin_used": round(estimated_initial_margin_used, 2),
            "estimated_maintenance_margin_used": round(estimated_maintenance_margin_used, 2),
            "estimated_open_risk_added_base": round(estimated_open_risk_added_base, 2),
            "post_trade_position_pct": round(post_trade_position_pct, 2),
            "post_trade_cash_base": round(post_trade_cash_base, 2),
            "post_trade_cash_pct": round(post_trade_cash_pct, 2),
            "observations": observations,
        }

    async def _resolve_last_price(self, conid: str, *, bars: list[Any] | None = None) -> float:
        if bars:
            return float(bars[-1].close)

        quotes = await self.market_data.get_quotes([conid])
        if quotes:
            raw_last = quotes[0].get("31")
            try:
                last = float(raw_last)
            except (TypeError, ValueError):
                last = 0.0
            if last > 0:
                return last

        bars_for_price = await self.market_data.get_historical_bars(
            conid=conid, period="1M", bar="1d"
        )
        if bars_for_price:
            return float(bars_for_price[-1].close)

        return 0.0

    async def _position_inputs(
        self, conid: str, *, stop_distance: float | None = None
    ) -> tuple[float | None, float, list[Any]]:
        bars: list[Any] = []
        derived_stop_distance = stop_distance

        if derived_stop_distance is None:
            bars = await self.market_data.get_historical_bars(conid=conid, period="1M", bar="1d")
            if bars:
                df = pd.DataFrame([{"high": b.high, "low": b.low, "close": b.close} for b in bars])
                atr = AverageTrueRange(df["high"], df["low"], df["close"], window=14)
                atr_val = atr.average_true_range().dropna()
                if not atr_val.empty:
                    derived_stop_distance = float(atr_val.iloc[-1]) * 1.5

        last_price = await self._resolve_last_price(conid, bars=bars)
        return derived_stop_distance, last_price, bars

    @staticmethod
    def _normalize_positions(raw_positions: list[dict[str, Any]]) -> list[dict[str, Any]]:
        positions = []
        for pos in raw_positions:
            symbol = str(pos.get("contractDesc") or pos.get("ticker") or "").upper()
            if not symbol:
                continue
            positions.append(
                {
                    "symbol": symbol,
                    "conid": str(pos.get("conid", "")),
                    "position": float(pos.get("position", 0) or 0),
                    "market_price": float(pos.get("mktPrice", 0) or 0),
                    "market_value": float(pos.get("mktValue", 0) or 0),
                    "currency": str(pos.get("currency") or ""),
                }
            )
        return positions

    @staticmethod
    def _normalize_live_orders(payload: Any) -> list[dict[str, Any]]:
        if isinstance(payload, dict):
            if isinstance(payload.get("orders"), list):
                return [item for item in payload["orders"] if isinstance(item, dict)]
            if isinstance(payload.get("data"), list):
                return [item for item in payload["data"] if isinstance(item, dict)]
            return []
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        return []

    @staticmethod
    def _estimate_base_to_quote_rate(
        summary: dict[str, Any],
        positions: list[dict[str, Any]],
        *,
        quote_currency: str | None = None,
    ) -> tuple[float, str]:
        normalized_quote_currency = str(quote_currency or "").upper()
        if normalized_quote_currency == BASE_CURRENCY:
            return 1.0, "base_currency"

        gross_position_value = float(summary.get("gross_position_value", 0) or 0)
        positions_with_currency = [p for p in positions if p.get("currency")]
        if positions_with_currency:
            base_native_total = sum(
                abs(p["market_value"])
                for p in positions_with_currency
                if str(p.get("currency") or "").upper() == BASE_CURRENCY
            )
            foreign_native_total = sum(
                abs(p["market_value"])
                for p in positions_with_currency
                if str(p.get("currency") or "").upper() != BASE_CURRENCY
            )
            foreign_value_budget = max(gross_position_value - base_native_total, 0.0)
            matching_native_total = sum(
                abs(p["market_value"])
                for p in positions_with_currency
                if str(p.get("currency") or "").upper() == normalized_quote_currency
            )
            if foreign_value_budget > 0 and matching_native_total > 0:
                return (
                    foreign_value_budget / matching_native_total,
                    "currency_specific_portfolio_implied",
                )
            if foreign_value_budget > 0 and foreign_native_total > 0:
                return (
                    foreign_value_budget / foreign_native_total,
                    "blended_foreign_portfolio_implied",
                )

        native_position_total = sum(abs(p["market_value"]) for p in positions if p["market_value"])
        if gross_position_value > 0 and native_position_total > 0:
            return gross_position_value / native_position_total, "portfolio_implied"

        return 1.0, "assumed_1.0"

    @staticmethod
    def _estimate_margin_profile(summary: dict[str, Any]) -> dict[str, float | str]:
        gross_position_value = float(summary.get("gross_position_value", 0) or 0)
        initial_margin = float(summary.get("initial_margin", 0) or 0)
        maintenance_margin = float(summary.get("maintenance_margin", 0) or 0)

        if gross_position_value > 0 and initial_margin > 0 and maintenance_margin > 0:
            return {
                "initial_margin_ratio": initial_margin / gross_position_value,
                "maintenance_margin_ratio": maintenance_margin / gross_position_value,
                "source": "portfolio_implied",
            }

        return {
            "initial_margin_ratio": 0.5,
            "maintenance_margin_ratio": 0.3,
            "source": "fallback_defaults",
        }

    @staticmethod
    def _pending_shares_for_symbol(
        symbol: str, conid: str, live_orders: list[dict[str, Any]]
    ) -> tuple[float, float]:
        pending_buy_shares = 0.0
        pending_sell_shares = 0.0

        for order in live_orders:
            status = str(order.get("status") or order.get("order_status") or "").lower()
            if status in {"filled", "cancelled", "inactive"}:
                continue

            order_symbol = str(
                order.get("ticker") or order.get("symbol") or order.get("contractDesc") or ""
            ).upper()
            order_conid = str(order.get("conid") or "")
            if order_symbol != symbol and order_conid != str(conid):
                continue

            qty = 0.0
            for key in ("remainingQuantity", "remainingSize", "quantity", "totalSize", "size"):
                raw_qty = order.get(key)
                if raw_qty is None:
                    continue
                try:
                    qty = float(raw_qty)
                    break
                except (TypeError, ValueError):
                    continue
            if qty <= 0:
                continue

            side = str(order.get("side") or "").upper()
            if side in {"BUY", "B"}:
                pending_buy_shares += qty
            elif side in {"SELL", "S"}:
                pending_sell_shares += qty

        return pending_buy_shares, pending_sell_shares

    async def stop_loss_levels(self, symbol: str, *, conid: str | None = None) -> dict[str, Any]:
        contract = await self.market_data.resolve_contract(symbol, conid=conid)
        bars = await self.market_data.get_historical_bars(
            conid=contract.conid, period="3M", bar="1d"
        )
        if not bars:
            return {"symbol": symbol.upper(), "error": "no data"}

        df = pd.DataFrame([{"high": b.high, "low": b.low, "close": b.close} for b in bars])
        close = df["close"]
        last = float(close.iloc[-1])

        atr = AverageTrueRange(df["high"], df["low"], close, window=14).average_true_range()
        atr_val = float(atr.dropna().iloc[-1]) if not atr.dropna().empty else 0

        levels = {}
        for multiplier, label in [
            (1.0, "tight"),
            (1.5, "moderate"),
            (2.0, "wide"),
            (3.0, "very_wide"),
        ]:
            distance = atr_val * multiplier
            levels[label] = {
                "atr_multiplier": multiplier,
                "stop_price": round(last - distance, 2),
                "distance": round(distance, 2),
                "distance_pct": round(distance / last * 100, 2) if last else 0,
            }

        recent_low = float(df["low"].tail(20).min())
        levels["recent_low_20d"] = {
            "stop_price": round(recent_low, 2),
            "distance": round(last - recent_low, 2),
            "distance_pct": round((last - recent_low) / last * 100, 2) if last else 0,
        }

        return {
            "symbol": symbol.upper(),
            "conid": contract.conid,
            "last_price": last,
            "atr_14": round(atr_val, 4),
            "levels": levels,
        }

    async def rebalance(self, target_allocation: dict[str, float]) -> dict[str, Any]:
        summary = await self.account_adapter.account_summary(self.account_id)
        nlv = float(summary.get("net_liquidation", 0) or 0)

        raw_positions = await self.order_adapter.portfolio_positions(self.account_id)
        current: dict[str, dict[str, Any]] = {}
        for pos in raw_positions:
            sym = pos.get("contractDesc") or pos.get("ticker", "")
            if sym:
                current[sym] = {
                    "market_value": float(pos.get("mktValue", 0) or 0),
                    "position": pos.get("position", 0),
                    "price": float(pos.get("mktPrice", 0) or 0),
                }

        trades_needed = []
        for symbol, target_pct in target_allocation.items():
            if symbol.upper() == "CASH":
                continue
            target_value = nlv * (target_pct / 100)
            current_value = current.get(symbol, {}).get("market_value", 0)
            diff = target_value - current_value
            price = current.get(symbol, {}).get("price", 0)

            if price <= 0:
                try:
                    contract = await self.market_data.resolve_contract(symbol)
                    bars = await self.market_data.get_historical_bars(
                        conid=contract.conid, period="1d", bar="1d"
                    )
                    if bars:
                        price = float(bars[-1].close)
                except Exception:
                    pass

            if abs(diff) < 10 or price <= 0:
                continue

            shares = int(diff / price)
            if shares == 0:
                continue

            trades_needed.append(
                {
                    "symbol": symbol,
                    "action": "BUY" if shares > 0 else "SELL",
                    "shares": abs(shares),
                    "estimated_value": round(abs(shares) * price, 2),
                    "current_allocation_pct": round(current_value / nlv * 100, 2) if nlv else 0,
                    "target_allocation_pct": target_pct,
                }
            )

        return {
            "account_value": nlv,
            "target_allocation": target_allocation,
            "trades_needed": trades_needed,
        }

    async def concentration(self) -> dict[str, Any]:
        summary = await self.account_adapter.account_summary(self.account_id)
        nlv = float(summary.get("net_liquidation", 0) or 0)

        raw_positions = await self.order_adapter.portfolio_positions(self.account_id)
        holdings = []
        for pos in raw_positions:
            mkt_value = float(pos.get("mktValue", 0) or 0)
            pct = (mkt_value / nlv * 100) if nlv else 0
            holdings.append(
                {
                    "symbol": pos.get("contractDesc") or pos.get("ticker", ""),
                    "market_value": mkt_value,
                    "allocation_pct": round(pct, 2),
                }
            )

        holdings.sort(key=lambda h: abs(h["allocation_pct"]), reverse=True)

        cash = float(summary.get("total_cash", 0) or 0)
        cash_pct = (cash / nlv * 100) if nlv else 0

        warnings = []
        for h in holdings:
            if abs(h["allocation_pct"]) > 25:
                warnings.append(f"{h['symbol']} at {h['allocation_pct']}% exceeds 25% threshold")
        if cash_pct < 5:
            warnings.append(f"Cash at {cash_pct:.1f}% is below 5% minimum")

        top5_pct = sum(h["allocation_pct"] for h in holdings[:5])

        return {
            "account_value": nlv,
            "cash": cash,
            "cash_pct": round(cash_pct, 2),
            "holdings": holdings,
            "top5_concentration_pct": round(top5_pct, 2),
            "warnings": warnings,
        }
