class RangeMeanReversionStrategy:
    name = "RANGE_MEAN_REVERSION"

    def evaluate(self, market, bars):
        if getattr(market, "regime", "") != "RANGE" or len(bars) < 60:
            return None

        c = bars[-1]
        window = bars[-30:]

        high = max(float(x["high"]) for x in window)
        low = min(float(x["low"]) for x in window)
        width = high - low

        if width <= 0:
            return None

        close = float(c["close"])
        open_ = float(c["open"])
        location = (close - low) / width

        near_bottom = location <= 0.20
        bullish_reversal = close > open_

        if near_bottom and bullish_reversal:
            return {
                "strategy": self.name,
                "side": "BUY",
                "entry": close,
                "invalidation": low * 0.997,
                "reason": "range_bottom_reversal",
                "range_location": location,
            }
        return None
