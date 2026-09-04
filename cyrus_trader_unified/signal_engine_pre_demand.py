from .architecture import TradeSignal
import bot_v5_2_balanced as b


class CyrusSignalEngine:
    """
    V6.3 structural entry:
    Breakout -> Retest -> Hold -> Confirmation
    """

    def find_signal(self, symbol, market):
        if market.regime != "TREND_UP":
            return None

        bars = b.get_bars(symbol, "5m", 100)
        if len(bars) < 80:
            return None

        closes = [x["close"] for x in bars]

        # Structure window excludes the four setup candles.
        structure = bars[-24:-4]
        breakout = bars[-4]
        retest = bars[-3]
        hold = bars[-2]
        confirm = bars[-1]

        resistance = max(x["high"] for x in structure)

        ef = b.ema(closes, b.CONFIG["ema_fast"])
        es = b.ema(closes, b.CONFIG["ema_slow"])
        atr = b.atr_pct(bars, b.CONFIG["atr_period"])

        if None in (ef, es, atr):
            return None

        # 1) Genuine breakout above prior structure.
        breakout_ok = (
            breakout["close"] > resistance
            and breakout["close"] > breakout["open"]
        )

        if not breakout_ok:
            return None

        # 2) Retest of the broken level.
        retest_ok = (
            retest["low"] <= resistance * 1.0015
            and retest["close"] >= resistance * 0.9985
        )

        if not retest_ok:
            return None

        # 3) Hold the reclaimed structure.
        hold_ok = (
            hold["close"] >= resistance
            and hold["low"] >= resistance * 0.9975
        )

        if not hold_ok:
            return None

        # 4) Continuation confirmation.
        confirm_ok = (
            confirm["close"] > hold["high"]
            and confirm["close"] > confirm["open"]
            and confirm["close"] > ef > es
        )

        if not confirm_ok:
            return None

        price = confirm["close"]

        extension_pct = price / resistance - 1.0
        if extension_pct < 0 or extension_pct > 0.0060:
            return None

        structure_low = min(
            retest["low"],
            hold["low"],
        )

        atr_buffer = min(atr * 0.20, 0.0020)
        invalidation = structure_low * (1.0 - atr_buffer)

        risk_pct = (price - invalidation) / price

        if risk_pct < 0.0020 or risk_pct > 0.0120:
            return None

        candle_move = (
            confirm["close"] / confirm["open"] - 1.0
            if confirm["open"] else 0.0
        )

        if candle_move < 0.0002 or candle_move > 0.0070:
            return None

        return TradeSignal(
            symbol=symbol,
            side="BUY",
            setup="BREAKOUT_RETEST_HOLD_CONFIRM",
            entry_price=price,
            invalidation_price=invalidation,
            confidence=1.0,
            metadata={
                "resistance": resistance,
                "extension_pct": extension_pct,
                "candle_move": candle_move,
                "atr_pct": atr,
                "risk_pct": risk_pct,
                "retest_low": retest["low"],
                "hold_low": hold["low"],
                "structure_low": structure_low,
                "tf15_mom3": market.tf15_mom3,
                "tf15_fast_slope": market.tf15_fast_slope,
                "tf1h_mom3": market.tf1h_mom3,
                "tf1h_fast_slope": market.tf1h_fast_slope,
            },
        )
