class BreakoutVolumeStrategy:
    name = "BREAKOUT_VOLUME"

    def evaluate(self, market, bars):
        if getattr(market, "regime", "") != "TREND_UP" or len(bars) < 60:
            return None

        c = bars[-1]
        history = bars[-21:-1]

        resistance = max(float(x["high"]) for x in history)
        avg_volume = sum(float(x["volume"]) for x in history) / len(history)

        close = float(c["close"])
        open_ = float(c["open"])
        volume = float(c["volume"])

        breakout = close > resistance
        bullish = close > open_
        volume_confirm = volume >= avg_volume * 1.35
        extension = close / resistance - 1.0

        if breakout and bullish and volume_confirm and 0 <= extension <= 0.006:
            return {
                "strategy": self.name,
                "side": "BUY",
                "entry": close,
                "invalidation": resistance * 0.996,
                "reason": "breakout_with_volume",
                "volume_ratio": volume / avg_volume,
            }
        return None
