import bot_v5_2_balanced as b
from cyrus_trader_v7.architecture import MarketContext


class CyrusMarketEngine:
    def evaluate(self, symbol: str) -> MarketContext:
        bars = b.get_bars(symbol)
        if len(bars) < 50:
            raise ValueError("not enough 5m candles")

        closes = [x["close"] for x in bars]
        price = closes[-1]

        ef = b.ema(closes, b.CONFIG["ema_fast"])
        es = b.ema(closes, b.CONFIG["ema_slow"])
        ef_prev = b.ema(closes[:-1], b.CONFIG["ema_fast"])
        atr = b.atr_pct(bars, b.CONFIG["atr_period"])

        if None in (ef, es, ef_prev, atr):
            raise ValueError("indicator data unavailable")

        tf15 = b.higher_tf_snapshot(
            symbol, "15m", b.CONFIG["mtf_15m_limit"]
        )
        tf1h = b.higher_tf_snapshot(
            symbol, "1h", b.CONFIG["mtf_1h_limit"]
        )

        trend_5m = (
            price > ef > es
            and ef > ef_prev
        )

        trend_15m = (
            tf15["price"] > tf15["ema_fast"] > tf15["ema_slow"]
            and tf15["fast_slope"] > 0
            and tf15["mom3"] > 0
        )

        trend_1h = (
            tf1h["price"] >= tf1h["ema_fast"] >= tf1h["ema_slow"]
            and tf1h["fast_slope"] >= 0
            and tf1h["mom3"] >= 0
        )

        def benchmark_safe(sym):
            try:
                x15 = b.higher_tf_snapshot(
                    sym, "15m", b.CONFIG["mtf_15m_limit"]
                )
                x1h = b.higher_tf_snapshot(
                    sym, "1h", b.CONFIG["mtf_1h_limit"]
                )
                return (
                    x15["price"] >= x15["ema_slow"]
                    and x15["mom3"] > -0.003
                    and x1h["price"] >= x1h["ema_slow"] * 0.995
                    and x1h["mom3"] > -0.008
                )
            except Exception:
                return False

        btc_safe = benchmark_safe("BTCUSDT")
        eth_safe = benchmark_safe("ETHUSDT")

        if atr >= 0.015:
            regime = "HIGH_VOL"
        elif not btc_safe and not eth_safe:
            regime = "RISK_OFF"
        elif trend_5m and trend_15m and trend_1h:
            regime = "TREND_UP"
        else:
            regime = "RANGE"

        return MarketContext(
            symbol=symbol,
            regime=regime,
            trend_5m=trend_5m,
            trend_15m=trend_15m,
            trend_1h=trend_1h,
            volatility=atr,
            btc_safe=btc_safe,
            eth_safe=eth_safe,
            tf15_mom3=float(tf15["mom3"]),
            tf15_fast_slope=float(tf15["fast_slope"]),
            tf1h_mom3=float(tf1h["mom3"]),
            tf1h_fast_slope=float(tf1h["fast_slope"]),
        )


if __name__ == "__main__":
    print("CYRUS V6 MARKET ENGINE OK")
