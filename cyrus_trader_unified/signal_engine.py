from .architecture import TradeSignal
import bot_v5_2_balanced as b


class CyrusSignalEngine:
    """
    CYRUS V7 demand entry:
    Breakout -> Retest -> Reclaim -> Demand -> Entry
    """

    def find_signal(self, symbol, market):
        if market.regime != "TREND_UP":
            return None

        bars = b.get_bars(symbol, "5m", 100)
        if len(bars) < 80:
            return None

        closes = [x["close"] for x in bars]

        # Four-candle setup. Entry occurs on the demand candle itself.
        structure = bars[-24:-4]
        breakout = bars[-4]
        retest = bars[-3]
        reclaim = bars[-2]
        demand = bars[-1]

        resistance = max(x["high"] for x in structure)

        ef = b.ema(closes, b.CONFIG["ema_fast"])
        es = b.ema(closes, b.CONFIG["ema_slow"])
        atr = b.atr_pct(bars, b.CONFIG["atr_period"])
        if None in (ef, es, atr):
            return None

        # 1) Break prior structure.
        if not (
            breakout["close"] > resistance
            and breakout["close"] > breakout["open"]
        ):
            return None

        # 2) Retest without decisive loss of the broken level.
        if not (
            retest["low"] <= resistance * 1.0015
            and retest["close"] >= resistance * 0.9975
        ):
            return None

        # 3) Reclaim and hold structure.
        if not (
            reclaim["close"] >= resistance
            and reclaim["close"] > reclaim["open"]
            and reclaim["low"] >= resistance * 0.9965
        ):
            return None

        # 4) Actual buyer demand.
        prior_volumes = [
            float(x.get("volume", 0.0))
            for x in bars[-21:-1]
        ]
        avg_volume = (
            sum(prior_volumes) / len(prior_volumes)
            if prior_volumes else 0.0
        )
        demand_volume = float(demand.get("volume", 0.0))
        volume_ratio = demand_volume / avg_volume if avg_volume > 0 else 0.0

        demand_range = demand["high"] - demand["low"]
        demand_body = demand["close"] - demand["open"]

        body_ratio = (
            demand_body / demand_range
            if demand_range > 0 else 0.0
        )
        close_location = (
            (demand["close"] - demand["low"]) / demand_range
            if demand_range > 0 else 0.0
        )

        demand_ok = (
            demand["close"] > demand["open"]
            and demand["close"] > reclaim["high"]
            and demand["close"] > resistance
            and demand["close"] > ef > es
            and volume_ratio >= 1.20
            and body_ratio >= 0.55
            and close_location >= 0.70
        )
        if not demand_ok:
            return None

        # Entry immediately after confirmed demand, avoiding an extra chase candle.
        price = demand["close"]
        extension_pct = price / resistance - 1.0
        if extension_pct < 0.0 or extension_pct > 0.0035:
            return None

        structure_low = min(
            retest["low"],
            reclaim["low"],
            demand["low"],
        )

        atr_buffer = min(atr * 0.20, 0.0020)
        invalidation = structure_low * (1.0 - atr_buffer)
        risk_pct = (price - invalidation) / price

        if risk_pct < 0.0020 or risk_pct > 0.0120:
            return None

        candle_move = (
            demand["close"] / demand["open"] - 1.0
            if demand["open"] else 0.0
        )
        if candle_move < 0.0002 or candle_move > 0.0070:
            return None

        return TradeSignal(
            symbol=symbol,
            side="BUY",
            setup="BREAKOUT_RETEST_RECLAIM_DEMAND",
            entry_price=price,
            invalidation_price=invalidation,
            confidence=1.0,
            metadata={
                "resistance": resistance,
                "extension_pct": extension_pct,
                "candle_move": candle_move,
                "atr_pct": atr,
                "risk_pct": risk_pct,
                "volume_ratio": volume_ratio,
                "demand_body_ratio": body_ratio,
                "demand_close_location": close_location,
                "retest_low": retest["low"],
                "hold_low": reclaim["low"],
                "structure_low": structure_low,
                "tf15_mom3": market.tf15_mom3,
                "tf15_fast_slope": market.tf15_fast_slope,
                "tf1h_mom3": market.tf1h_mom3,
                "tf1h_fast_slope": market.tf1h_fast_slope,
            },
        )
