from cyrus_trader_unified.architecture import TradeSignal, RiskDecision


class CyrusRiskEngine:
    def __init__(
        self,
        risk_per_trade=0.0025,
        max_position_fraction=0.05,
        max_drawdown=0.03,
        round_trip_cost_pct=0.0026,
    ):
        self.risk_per_trade = risk_per_trade
        self.max_position_fraction = max_position_fraction
        self.max_drawdown = max_drawdown
        self.round_trip_cost_pct = round_trip_cost_pct

    def evaluate(
        self,
        signal: TradeSignal,
        equity: float,
        portfolio_state: dict,
    ) -> RiskDecision:

        if equity <= 0:
            return RiskDecision(False, 0.0, 0.0, "NO_EQUITY")

        loss_streak = int(portfolio_state.get("loss_streak", 0))
        drawdown = float(portfolio_state.get("drawdown", 0.0))

        if drawdown >= self.max_drawdown:
            return RiskDecision(False, 0.0, 0.0, "MAX_DRAWDOWN")

        if loss_streak >= 3:
            return RiskDecision(False, 0.0, 0.0, "LOSS_STREAK_3")

        entry = float(signal.entry_price)
        stop = float(signal.invalidation_price)

        if stop >= entry or entry <= 0:
            return RiskDecision(False, 0.0, 0.0, "INVALID_STOP")

        stop_distance_pct = (entry - stop) / entry

        if stop_distance_pct <= 0:
            return RiskDecision(False, 0.0, 0.0, "ZERO_STOP_DISTANCE")

        risk_fraction = self.risk_per_trade

        if loss_streak == 2:
            risk_fraction *= 0.50
        elif loss_streak == 1:
            risk_fraction *= 0.75

        max_loss_usdt = equity * risk_fraction

        # Risk must include structural loss PLUS fee/slippage cost.
        effective_loss_pct = (
            stop_distance_pct + self.round_trip_cost_pct
        )

        spend_usdt = max_loss_usdt / effective_loss_pct

        # Hard portfolio exposure cap.
        spend_cap = equity * self.max_position_fraction
        spend_usdt = min(spend_usdt, spend_cap)

        if spend_usdt < 1.0:
            return RiskDecision(
                False,
                0.0,
                max_loss_usdt,
                "POSITION_TOO_SMALL"
            )

        return RiskDecision(
            approved=True,
            spend_usdt=spend_usdt,
            max_loss_usdt=max_loss_usdt,
            reason=(
                f"RISK_OK"
                f"|streak={loss_streak}"
                f"|stop={stop_distance_pct:.4f}"
                f"|cost={self.round_trip_cost_pct:.4f}"
                f"|effective={effective_loss_pct:.4f}"
                f"|risk=${max_loss_usdt:.4f}"
            ),
        )


if __name__ == "__main__":
    print("CYRUS V6 RISK ENGINE OK")
