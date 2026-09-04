class TrendPullbackStrategy:
    name = "TREND_PULLBACK"

    def evaluate(self, market, bars):
        if getattr(market, "regime", "") != "TREND_UP" or len(bars) < 60:
            return None

        c = bars[-1]
        p = bars[-2]
        ef = getattr(market, "ema_fast_5m", None)
        es = getattr(market, "ema_slow_5m", None)

        if not ef or not es or ef <= es:
            return None

        close = float(c["close"])
        open_ = float(c["open"])
        low = float(c["low"])
        prev_close = float(p["close"])

        pullback = low <= ef * 1.002
        reclaim = close > ef and close > open_
        continuation = close > prev_close

        if pullback and reclaim and continuation:
            return {
                "strategy": self.name,
                "side": "BUY",
                "entry": close,
                "invalidation": min(low, ef * 0.995),
                "reason": "trend_pullback_reclaim",
            }
        return None
