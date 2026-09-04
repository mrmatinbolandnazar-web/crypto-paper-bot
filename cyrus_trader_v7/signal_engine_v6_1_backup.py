import bot_v5_2_balanced as b
from cyrus_trader_v6.architecture import TradeSignal, MarketContext


class CyrusSignalEngine:
    def find_signal(self, symbol: str, market: MarketContext):
        if market.regime != "TREND_UP":
            return None

        bars = b.get_bars(symbol)
        if len(bars) < 50:
            return None

        closes = [x["close"] for x in bars]
        highs = [x["high"] for x in bars]
        lows = [x["low"] for x in bars]

        price = closes[-1]
        prev_close = closes[-2]

        ef = b.ema(closes, b.CONFIG["ema_fast"])
        es = b.ema(closes, b.CONFIG["ema_slow"])
        prev_ef = b.ema(closes[:-1], b.CONFIG["ema_fast"])
        atr = b.atr_pct(bars, b.CONFIG["atr_period"])

        if None in (ef, es, prev_ef, atr):
            return None

        prev_low = lows[-2]
        current_open = bars[-1]["open"]
        current_close = bars[-1]["close"]

        # Previous candle must actually pull back into the fast EMA zone.
        pullback = (
            prev_low <= prev_ef * 1.0015
            and prev_close <= prev_ef * 1.0010
        )

        # Current candle must reclaim fast EMA with positive body.
        reclaim = (
            prev_close <= prev_ef
            and current_close > ef
            and current_close > current_open
            and current_close > prev_close
        )

        # Do not buy an already stretched candle.
        extension = price / ef - 1.0
        clean_extension = 0.0 <= extension <= 0.0035

        # Avoid extreme short-term candle spikes.
        candle_move = current_close / prev_close - 1.0
        clean_candle = 0.0002 <= candle_move <= 0.0080

        if not all([pullback, reclaim, clean_extension, clean_candle]):
            return None

        # Structural invalidation:
        # below the pullback low, with a small ATR buffer.
        invalidation = prev_low * (1.0 - min(atr * 0.20, 0.0020))

        if invalidation >= price:
            return None

        risk_pct = (price - invalidation) / price

        # Reject setups whose structural stop is either unrealistically
        # tight or excessively wide.
        if risk_pct < 0.0020 or risk_pct > 0.0150:
            return None

        return TradeSignal(
            symbol=symbol,
            side="BUY",
            setup="TREND_PULLBACK_RECLAIM",
            entry_price=price,
            invalidation_price=invalidation,
            confidence=1.0,
            metadata={
                "ema_fast": ef,
                "ema_slow": es,
                "extension_pct": extension,
                "candle_move": candle_move,
                "atr_pct": atr,
                "risk_pct": risk_pct,
                "pullback_low": prev_low,
            },
        )


if __name__ == "__main__":
    print("CYRUS V6 SIGNAL ENGINE OK")
