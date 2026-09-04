import bot_v5_2_balanced as b


class CyrusPositionManager:
    def __init__(
        self,
        breakeven_r=0.60,
        trailing_r=1.00,
        trailing_atr_mult=1.20,
        max_hold_minutes=720,
        breakeven_cost_buffer=0.0025,
    ):
        self.breakeven_r = breakeven_r
        self.trailing_r = trailing_r
        self.trailing_atr_mult = trailing_atr_mult
        self.max_hold_minutes = max_hold_minutes
        self.breakeven_cost_buffer = breakeven_cost_buffer

    def manage(
        self,
        position: dict,
        symbol: str,
        age_minutes: float,
    ):
        bars = b.get_bars(symbol)

        if len(bars) < 40:
            return None

        closes = [x["close"] for x in bars]

        current = bars[-1]
        price = float(current["close"])
        candle_low = float(current["low"])

        entry = float(position["entry_price"])
        initial_stop = float(position["invalidation_price"])

        initial_risk = entry - initial_stop

        if initial_risk <= 0:
            return {
                "action": "EXIT",
                "price": price,
                "reason": "INVALID_INITIAL_RISK",
            }

        atr = b.atr_pct(bars, b.CONFIG["atr_period"])
        ef = b.ema(closes, b.CONFIG["ema_fast"])
        es = b.ema(closes, b.CONFIG["ema_slow"])

        if None in (atr, ef, es):
            return None

        highest = max(
            float(position.get("highest_price", entry)),
            float(current["high"]),
        )
        position["highest_price"] = highest

        r_multiple = (price - entry) / initial_risk
        mfe_r = (highest - entry) / initial_risk

        # 1) Emergency structural stop.
        active_stop = initial_stop

        # 2) Once price has moved +0.60R in our favor,
        # protect the trade near breakeven.
        if mfe_r >= self.breakeven_r:
            position["breakeven_armed"] = True

        if position.get("breakeven_armed"):
            active_stop = max(
                active_stop,
                entry * (1.0 + self.breakeven_cost_buffer),
            )

        # 3) After +1R, trail below the highest price.
        if mfe_r >= self.trailing_r:
            position["trailing_armed"] = True

        if position.get("trailing_armed"):
            trailing_stop = highest * (
                1.0 - atr * self.trailing_atr_mult
            )
            active_stop = max(active_stop, trailing_stop)

        position["active_stop"] = active_stop
        position["r_multiple"] = r_multiple
        position["mfe_r"] = mfe_r

        # Stop is evaluated against intrabar low.
        if candle_low <= active_stop:
            if position.get("trailing_armed"):
                reason = "V6_TRAILING_STOP"
            elif position.get("breakeven_armed"):
                reason = "V6_BREAKEVEN_STOP"
            else:
                reason = "V6_STRUCTURAL_STOP"

            return {
                "action": "EXIT",
                "price": active_stop,
                "reason": reason,
            }

        # 4) Structural failure:
        # fast EMA loses slow EMA and price closes below both.
        structure_lost = (
            price < ef
            and ef < es
        )

        if structure_lost:
            return {
                "action": "EXIT",
                "price": price,
                "reason": "V6_STRUCTURE_LOST",
            }

        # 5) Time stop: capital should not remain trapped forever.
        if age_minutes >= self.max_hold_minutes:
            return {
                "action": "EXIT",
                "price": price,
                "reason": "V6_TIME_EXIT",
            }

        return {
            "action": "HOLD",
            "active_stop": active_stop,
            "r_multiple": r_multiple,
            "mfe_r": mfe_r,
        }


if __name__ == "__main__":
    print("CYRUS V6 POSITION MANAGER OK")
