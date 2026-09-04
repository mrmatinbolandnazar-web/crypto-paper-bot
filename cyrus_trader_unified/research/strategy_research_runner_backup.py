
import csv
from collections import defaultdict
from pathlib import Path

from cyrus_trader_unified.strategies.trend_pullback import TrendPullbackStrategy
from cyrus_trader_unified.strategies.breakout_volume import BreakoutVolumeStrategy
from cyrus_trader_unified.strategies.range_mean_reversion import RangeMeanReversionStrategy

STRATEGIES = [
    TrendPullbackStrategy(),
    BreakoutVolumeStrategy(),
    RangeMeanReversionStrategy(),
]

def future_return(bars, i, horizon):
    if i + horizon >= len(bars):
        return None
    entry = float(bars[i]["close"])
    exit_ = float(bars[i + horizon]["close"])
    if entry <= 0:
        return None
    return exit_ / entry - 1.0

def summarize(name, vals):
    if not vals:
        return f"{name}: N=0"
    n = len(vals)
    wins = sum(x > 0 for x in vals)
    avg = sum(vals) / n
    pos = sum(x for x in vals if x > 0)
    neg = abs(sum(x for x in vals if x < 0))
    pf = (pos / neg) if neg else float("inf")
    return f"{name}: N={n} WR={wins/n*100:.1f}% AVG={avg*100:.4f}% PF={pf:.2f}"

def main():
    print("CYRUS UNIFIED STRATEGY RESEARCH RUNNER")
    print("READY")
    print("Strategies:", ", ".join(s.name for s in STRATEGIES))
    print("Evaluation horizons: 3, 6, 12 candles")
    print("Mode: signal-quality research before execution/risk")
    print("NEXT: connect historical replay feed")

if __name__ == "__main__":
    main()
