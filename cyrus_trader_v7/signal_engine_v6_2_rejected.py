from .architecture import TradeSignal
import bot_v5_2_balanced as b


class CyrusSignalEngine:
    """
    V6.2 structural entry:
    Pullback -> Reclaim -> Continuation
    """

    def find_signal(self, symbol, market):
        if market.regime != "TREND_UP":
            return None

        bars = b.get_bars(symbol, "5m", 80)
        if len(bars) < 60:
            return None

        closes = [x["close"] for x in bars]

        # Three-stage completed sequence
        pull = bars[-3]
        reclaim = bars[-2]
        confirm = bars[-1]

        pull_ef = b.ema(closes[:-2], 9)
        reclaim_ef = b.ema(closes[:-1], 9)
        confirm_ef = b.ema(closes, 9)

        price = confirm["close"]
        atr = b.atr_pct(bars, b.CONFIG["atr_period"])

        # 1) Pullback into value / EMA area.
        pullback_ok = (
            pull["low"] <= pull_ef * 1.0015
            and pull["close"] <= pull_ef * 1.0010
        )

        # 2) Genuine reclaim.
        reclaim_ok = (
            reclaim["close"] > reclaim_ef
            and reclaim["close"] > reclaim["open"]
            and reclaim["close"] > pull["close"]
        )

        # 3) Continuation confirmation.
        # We no longer buy directly on the reclaim candle.
        continuation_ok = (
            price > confirm_ef
            and price > reclaim["high"]
            and price > confirm["open"]
        )

        if not (pullback_ok and reclaim_ok and continuation_ok):
            return None

        extension_pct = (price / confirm_ef) - 1.0
        candle_move = (price / confirm["open"]) - 1.0

        # Prevent chasing an already-extended confirmation candle.
        if extension_pct < 0 or extension_pct > 0.0035:
            return None

        if candle_move < 0.0002 or candle_move > 0.0070:
            return None

        # Structural invalidation beneath the actual pullback/reclaim structure.
        structure_low = min(pull["low"], reclaim["low"])
        buffer_pct = min(atr * 0.20, 0.0020)
        invalidation = structure_low * (1.0 - buffer_pct)

        if invalidation >= price:
            return None

        risk_pct = (price - invalidation) / price

        if risk_pct < 0.0020 or risk_pct > 0.0120:
            return None

        return TradeSignal(
            symbol=symbol,
            side="BUY",
            setup="TREND_PULLBACK_RECLAIM_CONTINUATION",
            entry_price=price,
            invalidation_price=invalidation,
            confidence=1.0,
            metadata={
                "ema_fast": confirm_ef,
                "extension_pct": extension_pct,
                "candle_move": candle_move,
                "atr_pct": atr,
                "risk_pct": risk_pct,
                "pullback_low": pull["low"],
                "reclaim_high": reclaim["high"],
                "structure_low": structure_low,
            },
        )
