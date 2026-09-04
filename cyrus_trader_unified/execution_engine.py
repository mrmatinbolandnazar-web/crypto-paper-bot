from cyrus_trader_unified.architecture import TradeSignal, RiskDecision


class CyrusExecutionEngine:
    def __init__(
        self,
        fee_rate=0.0010,
        slippage_rate=0.0003,
    ):
        self.fee_rate = fee_rate
        self.slippage_rate = slippage_rate

    def open_position(
        self,
        signal: TradeSignal,
        risk: RiskDecision,
        portfolio_state: dict,
        time_utc: str,
    ):
        if not risk.approved:
            return None

        if signal.side != "BUY":
            return None

        raw_price = float(signal.entry_price)
        exec_price = raw_price * (1.0 + self.slippage_rate)

        spend = float(risk.spend_usdt)
        fee = spend * self.fee_rate
        net_spend = spend - fee

        if exec_price <= 0 or net_spend <= 0:
            return None

        qty = net_spend / exec_price

        position = {
            "symbol": signal.symbol,
            "side": "LONG",
            "setup": signal.setup,
            "entry_time": time_utc,
            "signal_price": raw_price,
            "entry_price": exec_price,
            "qty": qty,
            "gross_spend_usdt": spend,
            "entry_fee_usdt": fee,
            "invalidation_price": float(signal.invalidation_price),
            "max_loss_usdt": float(risk.max_loss_usdt),
            "highest_price": exec_price,
            "breakeven_armed": False,
            "trailing_armed": False,
            "metadata": dict(signal.metadata),
        }

        return position

    def close_position(
        self,
        position: dict,
        raw_exit_price: float,
        reason: str,
        time_utc: str,
    ):
        exec_price = float(raw_exit_price) * (1.0 - self.slippage_rate)

        qty = float(position["qty"])
        gross_value = qty * exec_price
        exit_fee = gross_value * self.fee_rate

        entry_cost = float(position["gross_spend_usdt"])
        net_value = gross_value - exit_fee
        realized_pnl = net_value - entry_cost

        return {
            "symbol": position["symbol"],
            "setup": position["setup"],
            "entry_time": position["entry_time"],
            "exit_time": time_utc,
            "entry_price": position["entry_price"],
            "exit_price": exec_price,
            "qty": qty,
            "gross_spend_usdt": entry_cost,
            "entry_fee_usdt": position["entry_fee_usdt"],
            "exit_fee_usdt": exit_fee,
            "realized_pnl_usdt": realized_pnl,
            "reason": reason,
            "extension_pct": position.get("metadata", {}).get("extension_pct"),
            "candle_move": position.get("metadata", {}).get("candle_move"),
            "atr_pct": position.get("metadata", {}).get("atr_pct"),
            "risk_pct": position.get("metadata", {}).get("risk_pct"),
            "tf15_mom3": position.get("metadata", {}).get("tf15_mom3"),
            "tf15_fast_slope": position.get("metadata", {}).get("tf15_fast_slope"),
            "tf1h_mom3": position.get("metadata", {}).get("tf1h_mom3"),
            "tf1h_fast_slope": position.get("metadata", {}).get("tf1h_fast_slope"),
        }


if __name__ == "__main__":
    print("CYRUS V6 EXECUTION ENGINE OK")
