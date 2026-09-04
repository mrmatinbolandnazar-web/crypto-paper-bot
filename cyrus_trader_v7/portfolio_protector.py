from datetime import datetime, timezone, timedelta


class CyrusPortfolioProtector:
    def __init__(
        self,
        max_drawdown=0.03,
        max_daily_loss=0.01,
        max_loss_streak=3,
        cooldown_minutes=60,
    ):
        self.max_drawdown = max_drawdown
        self.max_daily_loss = max_daily_loss
        self.max_loss_streak = max_loss_streak
        self.cooldown_minutes = cooldown_minutes

    def _to_dt(self, value=None):
        if value is None:
            return datetime.now(timezone.utc)

        if isinstance(value, datetime):
            dt = value
        else:
            dt = datetime.fromisoformat(str(value))

        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)

        return dt

    def allow_new_trade(
        self,
        portfolio_state: dict,
        now_time=None,
    ) -> bool:
        allowed, _ = self.check(
            portfolio_state,
            now_time,
        )
        return allowed

    def check(
        self,
        portfolio_state: dict,
        now_time=None,
    ):
        now = self._to_dt(now_time)

        drawdown = float(
            portfolio_state.get("drawdown", 0.0)
        )
        daily_pnl_pct = float(
            portfolio_state.get("daily_pnl_pct", 0.0)
        )
        loss_streak = int(
            portfolio_state.get("loss_streak", 0)
        )

        if drawdown >= self.max_drawdown:
            return False, "PORTFOLIO_DRAWDOWN_LOCK"

        if daily_pnl_pct <= -self.max_daily_loss:
            return False, "DAILY_LOSS_LOCK"

        cooldown_until = portfolio_state.get(
            "protector_cooldown_until"
        )

        if cooldown_until:
            try:
                dt = self._to_dt(cooldown_until)
            except Exception:
                return False, "INVALID_COOLDOWN_STATE"

            if now < dt:
                return False, "PROTECTOR_COOLDOWN"

            # Cooldown completed:
            # allow the strategy to prove itself again.
            portfolio_state.pop(
                "protector_cooldown_until",
                None,
            )
            portfolio_state["loss_streak"] = 0
            loss_streak = 0

        if loss_streak >= self.max_loss_streak:
            until = now + timedelta(
                minutes=self.cooldown_minutes
            )
            portfolio_state[
                "protector_cooldown_until"
            ] = until.isoformat()

            return False, "LOSS_STREAK_COOLDOWN"

        return True, "PROTECTION_OK"

    def update_after_trade(
        self,
        portfolio_state: dict,
        realized_pnl: float,
        equity_before: float,
        time_utc=None,
    ):
        if realized_pnl < 0:
            portfolio_state["loss_streak"] = (
                int(
                    portfolio_state.get(
                        "loss_streak", 0
                    )
                ) + 1
            )
        else:
            portfolio_state["loss_streak"] = 0
            portfolio_state.pop(
                "protector_cooldown_until",
                None,
            )

        if equity_before > 0:
            daily_pnl = float(
                portfolio_state.get(
                    "daily_pnl_usdt", 0.0
                )
            )
            daily_pnl += realized_pnl

            portfolio_state[
                "daily_pnl_usdt"
            ] = daily_pnl

            portfolio_state[
                "daily_pnl_pct"
            ] = daily_pnl / equity_before

        return portfolio_state


if __name__ == "__main__":
    print("CYRUS V6 PORTFOLIO PROTECTOR V2 OK")
