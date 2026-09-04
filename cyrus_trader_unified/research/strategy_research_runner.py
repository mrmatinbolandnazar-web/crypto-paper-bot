import json
from pathlib import Path
from types import SimpleNamespace
from collections import defaultdict

from cyrus_trader_unified.strategies.trend_pullback import TrendPullbackStrategy
from cyrus_trader_unified.strategies.breakout_volume import BreakoutVolumeStrategy
from cyrus_trader_unified.strategies.range_mean_reversion import RangeMeanReversionStrategy

CACHE = Path("/opt/crypto-paper-bot/.backtest_cache_v5_2")
START_MS = 1784901900000   # 2026-07-24 14:05 UTC
END_MS   = 1787839500000   # 2026-08-27 14:05 UTC
ROUND_TRIP_COST = 0.0026

STRATEGIES = [
    TrendPullbackStrategy(),
    BreakoutVolumeStrategy(),
    RangeMeanReversionStrategy(),
]

def ema(values, period):
    if len(values) < period:
        return None
    a = 2.0 / (period + 1.0)
    e = sum(values[:period]) / period
    for v in values[period:]:
        e = v * a + e * (1.0 - a)
    return e

def normalize(raw):
    out = []
    for x in raw:
        if isinstance(x, dict):
            ct = x.get("close_time", x.get("closeTime", x.get("time", x.get("timestamp"))))
            if ct is None:
                continue
            out.append({
                "time": int(ct),
                "open": float(x["open"]),
                "high": float(x["high"]),
                "low": float(x["low"]),
                "close": float(x["close"]),
                "volume": float(x["volume"]),
            })
        else:
            # Binance kline format
            if len(x) < 7:
                continue
            out.append({
                "time": int(x[6]),
                "open": float(x[1]),
                "high": float(x[2]),
                "low": float(x[3]),
                "close": float(x[4]),
                "volume": float(x[5]),
            })
    return out

def load_symbol(symbol):
    candidates = [
        CACHE / f"{symbol}_5m_20260724_20260827.json",
        CACHE / f"{symbol}_5m_20260525_20260827.json",
    ]
    for p in candidates:
        if p.exists():
            try:
                raw = json.loads(p.read_text())
                bars = normalize(raw)
                bars = [b for b in bars if START_MS <= b["time"] <= END_MS]
                if len(bars) >= 100:
                    return bars
            except Exception:
                pass
    return []

def classify_market(window):
    closes = [x["close"] for x in window]
    e20 = ema(closes[-60:], 20)
    e50 = ema(closes[-80:], 50)
    prev20 = ema(closes[-61:-1], 20)

    if e20 is None or e50 is None or prev20 is None:
        return None

    close = closes[-1]

    if close > e20 > e50 and e20 > prev20:
        regime = "TREND_UP"
    else:
        spread = abs(e20 / e50 - 1.0)
        regime = "RANGE" if spread < 0.006 else "RISK_OFF"

    return SimpleNamespace(
        regime=regime,
        ema_fast_5m=e20,
        ema_slow_5m=e50,
    )

def pf(vals):
    pos = sum(x for x in vals if x > 0)
    neg = abs(sum(x for x in vals if x < 0))
    if neg == 0:
        return float("inf") if pos > 0 else 0.0
    return pos / neg

def main():
    files = sorted(CACHE.glob("*_5m_20260525_20260827.json"))
    symbols = sorted({p.name.split("_5m_")[0] for p in files})

    stats = {
        s.name: {3: [], 6: [], 12: []}
        for s in STRATEGIES
    }
    signals = defaultdict(int)
    loaded = 0

    for symbol in symbols:
        bars = load_symbol(symbol)
        if not bars:
            continue

        loaded += 1

        for i in range(80, len(bars) - 12):
            window = bars[:i+1] if i < 100 else bars[i-99:i+1]
            market = classify_market(window)
            if market is None:
                continue

            for strategy in STRATEGIES:
                sig = strategy.evaluate(market, window)
                if not sig:
                    continue

                signals[strategy.name] += 1
                entry = bars[i]["close"]

                for h in (3, 6, 12):
                    exit_price = bars[i+h]["close"]
                    gross = exit_price / entry - 1.0
                    net = gross - ROUND_TRIP_COST
                    stats[strategy.name][h].append(net)

    print("CYRUS UNIFIED - BULL 34D SIGNAL RESEARCH")
    print(f"Symbols loaded: {loaded}")
    print(f"Round-trip cost assumption: {ROUND_TRIP_COST*100:.2f}%")
    print()

    for strategy in STRATEGIES:
        name = strategy.name
        print("=" * 66)
        print(f"{name} | SIGNALS={signals[name]}")
        for h, minutes in ((3,15),(6,30),(12,60)):
            vals = stats[name][h]
            if not vals:
                print(f"{minutes:>2}m | N=0")
                continue

            wins = sum(v > 0 for v in vals)
            avg = sum(vals) / len(vals)
            print(
                f"{minutes:>2}m | N={len(vals):5d} "
                f"WR={wins/len(vals)*100:5.1f}% "
                f"NET_AVG={avg*100:+.4f}% "
                f"PF={pf(vals):.2f}"
            )

    print()
    print("RULE: We only promote a strategy if the edge survives costs.")
    print("No parameter tuning performed.")

if __name__ == "__main__":
    main()
