#!/usr/bin/env python3
# V5.5 Crowd Psychology / FOMO / Trap Shadow
# OBSERVATION ONLY - NEVER BUYS OR SELLS.

import csv
import json
import math
import os
from datetime import datetime, timezone
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import bot_v5_2 as b

FUTURES_BASE = "https://fapi.binance.com"

CSV_FILE = "crowd_psychology_v5_5.csv"
LATEST_FILE = "crowd_psychology_v5_5_latest.txt"

MAX_SYMBOLS = 12
MIN_QUOTE_VOLUME = 10_000_000.0
HTTP_TIMEOUT = 12
PERIOD = "5m"


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def clamp(x, lo=0.0, hi=1.0):
    return max(lo, min(hi, x))


def scale(x, lo, hi):
    if x is None or hi <= lo:
        return 0.0
    return clamp((x - lo) / (hi - lo))


def inv_scale(x, lo, hi):
    if x is None:
        return 0.0
    return 1.0 - scale(x, lo, hi)


def safe_float(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def futures_get(path, params=None):
    params = params or {}
    url = FUTURES_BASE + path
    if params:
        url += "?" + urlencode(params)

    req = Request(
        url,
        headers={"User-Agent": "v5.5-crowd-psychology-shadow/1.0"}
    )

    with urlopen(req, timeout=HTTP_TIMEOUT) as r:
        return json.loads(r.read().decode("utf-8"))


def get_futures_symbols():
    data = futures_get("/fapi/v1/exchangeInfo")
    return {
        x.get("symbol")
        for x in data.get("symbols", [])
        if (
            x.get("status") == "TRADING"
            and x.get("quoteAsset") == "USDT"
            and x.get("contractType") == "PERPETUAL"
        )
    }


def latest_ratio(path, symbol):
    rows = futures_get(
        path,
        {"symbol": symbol, "period": PERIOD, "limit": 3}
    )

    if not isinstance(rows, list) or not rows:
        return None

    return safe_float(rows[-1].get("longShortRatio"))


def latest_taker(symbol):
    rows = futures_get(
        "/futures/data/takerlongshortRatio",
        {"symbol": symbol, "period": PERIOD, "limit": 3}
    )

    if not isinstance(rows, list) or not rows:
        return None

    return safe_float(rows[-1].get("buySellRatio"))


def latest_oi_change(symbol):
    rows = futures_get(
        "/futures/data/openInterestHist",
        {"symbol": symbol, "period": PERIOD, "limit": 3}
    )

    if not isinstance(rows, list) or len(rows) < 2:
        return None

    for key in ("sumOpenInterestValue", "sumOpenInterest"):
        old = safe_float(rows[-2].get(key))
        new = safe_float(rows[-1].get(key))

        if old is not None and new is not None and old > 0:
            return new / old - 1.0

    return None


def latest_funding(symbol):
    data = futures_get(
        "/fapi/v1/premiumIndex",
        {"symbol": symbol}
    )

    if not isinstance(data, dict):
        return None

    return safe_float(data.get("lastFundingRate"))


def psychology_level(price):
    if price <= 0:
        return None, 1.0

    if price >= 50000:
        step = 5000
    elif price >= 10000:
        step = 1000
    elif price >= 1000:
        step = 100
    elif price >= 100:
        step = 10
    elif price >= 10:
        step = 1
    elif price >= 1:
        step = 0.10
    elif price >= 0.10:
        step = 0.01
    elif price >= 0.01:
        step = 0.001
    elif price >= 0.001:
        step = 0.0001
    else:
        exponent = math.floor(math.log10(price))
        step = 10 ** exponent

    level = round(price / step) * step

    if level <= 0:
        return None, 1.0

    distance = abs(price / level - 1.0)
    return level, distance


def build_candidates():
    _, ticker_map = b.get_market_catalog()
    futures_symbols = get_futures_symbols()

    ranked = []

    for symbol, t in ticker_map.items():
        if symbol not in futures_symbols:
            continue

        qv = float(t.get("quote_volume", 0.0) or 0.0)
        chg = float(t.get("change_pct", 0.0) or 0.0)

        if qv < MIN_QUOTE_VOLUME:
            continue

        # Preference for liquid instruments with meaningful movement.
        movement = abs(chg)
        liquidity = math.log10(max(qv, 1.0))

        rank = movement * 1.25 + liquidity * 0.40

        ranked.append((rank, symbol, qv, chg))

    ranked.sort(reverse=True)

    selected = []

    # BTC and ETH always stay visible to the psychology layer.
    for symbol in ("BTCUSDT", "ETHUSDT"):
        if symbol in futures_symbols and symbol in ticker_map:
            t = ticker_map[symbol]
            selected.append({
                "symbol": symbol,
                "change24": float(t.get("change_pct", 0.0) or 0.0),
                "quote_volume": float(t.get("quote_volume", 0.0) or 0.0),
            })

    for _, symbol, qv, chg in ranked:
        if any(x["symbol"] == symbol for x in selected):
            continue

        selected.append({
            "symbol": symbol,
            "change24": chg,
            "quote_volume": qv,
        })

        if len(selected) >= MAX_SYMBOLS:
            break

    return selected


def spot_snapshot(symbol):
    bars = b.get_bars(symbol, "5m", 80)

    if len(bars) < 30:
        raise ValueError("not enough closed 5m bars")

    closes = [x["close"] for x in bars]
    vols = [x["volume"] for x in bars]

    price = closes[-1]

    mom5 = price / closes[-2] - 1.0
    mom15 = price / closes[-4] - 1.0
    mom30 = price / closes[-7] - 1.0

    rr = b.rsi(closes, b.CONFIG["rsi_period"])
    atr = b.atr_pct(bars, b.CONFIG["atr_period"])

    if rr is None or atr is None:
        raise ValueError("indicator data unavailable")

    previous_volumes = vols[-21:-1]
    avg_volume = (
        sum(previous_volumes) / len(previous_volumes)
        if previous_volumes else 0.0
    )

    volume_ratio = (
        vols[-1] / avg_volume
        if avg_volume > 0 else 0.0
    )

    recent = bars[-25:-1]

    recent_high = max(x["high"] for x in recent)
    recent_low = min(x["low"] for x in recent)

    range_size = max(
        recent_high - recent_low,
        price * 0.000001
    )

    range_position = clamp(
        (price - recent_low) / range_size
    )

    high_distance = max(
        0.0,
        recent_high / price - 1.0
    )

    low_distance = max(
        0.0,
        price / recent_low - 1.0
    )

    round_level, round_distance = psychology_level(price)

    return {
        "price": price,
        "rsi": rr,
        "atr": atr,
        "mom5": mom5,
        "mom15": mom15,
        "mom30": mom30,
        "volume_ratio": volume_ratio,
        "recent_high": recent_high,
        "recent_low": recent_low,
        "range_position": range_position,
        "high_distance": high_distance,
        "low_distance": low_distance,
        "round_level": round_level,
        "round_distance": round_distance,
    }


def psychology_snapshot(symbol, spot):
    top_position = latest_ratio(
        "/futures/data/topLongShortPositionRatio",
        symbol
    )

    top_account = latest_ratio(
        "/futures/data/topLongShortAccountRatio",
        symbol
    )

    global_ratio = latest_ratio(
        "/futures/data/globalLongShortAccountRatio",
        symbol
    )

    taker_ratio = latest_taker(symbol)
    oi_change = latest_oi_change(symbol)
    funding = latest_funding(symbol)

    coverage = sum(
        x is not None
        for x in (
            top_position,
            top_account,
            global_ratio,
            taker_ratio,
            oi_change,
            funding,
        )
    )

    near_high = clamp(
        1.0 - spot["high_distance"] / 0.015
    )

    near_low = clamp(
        1.0 - spot["low_distance"] / 0.015
    )

    near_round = clamp(
        1.0 - spot["round_distance"] / 0.008
    )

    positive_momentum = (
        0.35 * scale(spot["mom5"], 0.0000, 0.0120)
        + 0.40 * scale(spot["mom15"], 0.0010, 0.0250)
        + 0.25 * scale(spot["mom30"], 0.0020, 0.0400)
    )

    negative_momentum = (
        0.40 * inv_scale(spot["mom5"], -0.0120, 0.0000)
        + 0.35 * inv_scale(spot["mom15"], -0.0300, 0.0000)
        + 0.25 * inv_scale(spot["mom30"], -0.0450, 0.0000)
    )

    volume_heat = scale(
        spot["volume_ratio"],
        0.90,
        3.00
    )

    taker_buy = scale(
        taker_ratio,
        1.00,
        1.60
    )

    taker_sell = inv_scale(
        taker_ratio,
        0.55,
        1.00
    )

    oi_build = scale(
        oi_change,
        0.0000,
        0.0300
    )

    oi_flush = inv_scale(
        oi_change,
        -0.0300,
        0.0000
    )

    long_crowd = (
        0.45 * scale(global_ratio, 1.00, 1.80)
        + 0.35 * scale(top_position, 1.00, 2.50)
        + 0.20 * scale(top_account, 1.00, 1.80)
    )

    short_crowd = (
        0.45 * inv_scale(global_ratio, 0.55, 1.00)
        + 0.35 * inv_scale(top_position, 0.55, 1.00)
        + 0.20 * inv_scale(top_account, 0.55, 1.00)
    )

    funding_long_heat = scale(
        funding,
        0.00010,
        0.00100
    )

    rsi_fomo = scale(
        spot["rsi"],
        55.0,
        76.0
    )

    rsi_panic = inv_scale(
        spot["rsi"],
        18.0,
        42.0
    )

    # Traders become tempted when momentum, aggressive buying,
    # rising OI, volume and obvious breakout/round-number areas combine.
    temptation = clamp(
        0.23 * positive_momentum
        + 0.19 * volume_heat
        + 0.16 * taker_buy
        + 0.14 * oi_build
        + 0.11 * near_high
        + 0.08 * near_round
        + 0.09 * rsi_fomo
    )

    # Long-trap risk rises when the crowd becomes long and hot,
    # but immediate momentum starts to stall near an obvious high.
    momentum_stall = 0.0

    if spot["mom15"] > 0.003:
        if spot["mom5"] <= 0:
            momentum_stall = 1.0
        elif spot["mom5"] < spot["mom15"] / 3.0:
            momentum_stall = 0.65

    trap_risk = clamp(
        0.24 * temptation
        + 0.20 * long_crowd
        + 0.14 * funding_long_heat
        + 0.14 * oi_build
        + 0.13 * near_high
        + 0.15 * momentum_stall
    )

    # Shorts crowded + buyers becoming aggressive + OI building
    # near resistance can create squeeze conditions.
    squeeze_score = clamp(
        0.29 * short_crowd
        + 0.22 * taker_buy
        + 0.17 * oi_build
        + 0.15 * near_high
        + 0.17 * positive_momentum
    )

    # Panic exhaustion looks for oversold price, heavy selling,
    # volume spike and liquidation / OI flush near recent lows.
    panic_score = clamp(
        0.23 * rsi_panic
        + 0.22 * negative_momentum
        + 0.18 * volume_heat
        + 0.14 * near_low
        + 0.13 * taker_sell
        + 0.10 * oi_flush
    )

    if coverage < 4:
        confidence = "DATA_WEAK"
    elif coverage == 6:
        confidence = "HIGH"
    else:
        confidence = "MEDIUM"

    if (
        temptation >= 0.58
        and trap_risk >= 0.62
    ):
        verdict = "DO_NOT_CHASE_LONG_TRAP"

    elif squeeze_score >= 0.68:
        verdict = "SHORT_SQUEEZE_WATCH"

    elif panic_score >= 0.68:
        verdict = "PANIC_EXHAUSTION_WATCH"

    elif temptation >= 0.70:
        verdict = "FOMO_BUILDING"

    elif (
        temptation >= 0.50
        and trap_risk < 0.48
    ):
        verdict = "EARLY_INTEREST"

    elif trap_risk >= 0.62:
        verdict = "CROWD_TRAP_RISK"

    else:
        verdict = "NEUTRAL"

    return {
        "temptation": temptation,
        "trap_risk": trap_risk,
        "squeeze_score": squeeze_score,
        "panic_score": panic_score,
        "verdict": verdict,
        "confidence": confidence,
        "coverage": coverage,
        "top_position": top_position,
        "top_account": top_account,
        "global_ratio": global_ratio,
        "taker_ratio": taker_ratio,
        "oi_change": oi_change,
        "funding": funding,
    }


def ensure_csv():
    if os.path.exists(CSV_FILE):
        return

    with open(
        CSV_FILE,
        "w",
        newline="",
        encoding="utf-8"
    ) as f:

        csv.writer(f).writerow([
            "time_utc",
            "symbol",
            "change24_pct",
            "price",
            "rsi",
            "mom5_pct",
            "mom15_pct",
            "mom30_pct",
            "volume_ratio",
            "temptation_score",
            "trap_risk",
            "squeeze_score",
            "panic_score",
            "verdict",
            "confidence",
            "coverage",
            "global_ratio",
            "top_position_ratio",
            "top_account_ratio",
            "taker_ratio",
            "oi_change_pct",
            "funding_pct",
            "round_level",
            "round_distance_pct",
        ])


def fmt(x, digits=3):
    if x is None:
        return "NA"
    return f"{x:.{digits}f}"


def main():
    print("=" * 100)
    print("V5.5 CROWD PSYCHOLOGY / FOMO / TRAP SHADOW")
    print("Behavior inference only - no real or paper trading decisions are changed.")
    print("=" * 100)

    stamp = now_iso()
    candidates = build_candidates()

    print(f"Candidates: {len(candidates)}")

    ensure_csv()

    results = []

    for item in candidates:
        symbol = item["symbol"]

        try:
            spot = spot_snapshot(symbol)
            psy = psychology_snapshot(symbol, spot)

        except Exception as exc:
            print(f"{symbol:12} ERROR {exc}")
            continue

        result = {
            **item,
            **spot,
            **psy,
        }

        results.append(result)

        print(
            f"{symbol:12} "
            f"24h={item['change24']:+6.2f}% "
            f"RSI={spot['rsi']:5.1f} "
            f"M15={spot['mom15']*100:+5.2f}% "
            f"VOLx={spot['volume_ratio']:4.2f} | "
            f"TEMPT={psy['temptation']*100:5.1f} "
            f"TRAP={psy['trap_risk']*100:5.1f} "
            f"SQZ={psy['squeeze_score']*100:5.1f} "
            f"PANIC={psy['panic_score']*100:5.1f} | "
            f"{psy['verdict']} "
            f"cov={psy['coverage']}/6"
        )

        with open(
            CSV_FILE,
            "a",
            newline="",
            encoding="utf-8"
        ) as f:

            csv.writer(f).writerow([
                stamp,
                symbol,
                f"{item['change24']:.4f}",
                f"{spot['price']:.10f}",
                f"{spot['rsi']:.4f}",
                f"{spot['mom5']*100:.4f}",
                f"{spot['mom15']*100:.4f}",
                f"{spot['mom30']*100:.4f}",
                f"{spot['volume_ratio']:.4f}",
                f"{psy['temptation']:.4f}",
                f"{psy['trap_risk']:.4f}",
                f"{psy['squeeze_score']:.4f}",
                f"{psy['panic_score']:.4f}",
                psy["verdict"],
                psy["confidence"],
                psy["coverage"],
                fmt(psy["global_ratio"], 5),
                fmt(psy["top_position"], 5),
                fmt(psy["top_account"], 5),
                fmt(psy["taker_ratio"], 5),
                (
                    "NA"
                    if psy["oi_change"] is None
                    else f"{psy['oi_change']*100:.5f}"
                ),
                (
                    "NA"
                    if psy["funding"] is None
                    else f"{psy['funding']*100:.6f}"
                ),
                (
                    "NA"
                    if spot["round_level"] is None
                    else f"{spot['round_level']:.10f}"
                ),
                f"{spot['round_distance']*100:.4f}",
            ])

    results.sort(
        key=lambda x: x["temptation"],
        reverse=True
    )

    out = [
        "V5.5 CROWD PSYCHOLOGY SHADOW",
        f"Updated UTC: {stamp}",
        f"Candidates analyzed: {len(results)}",
        "Mode: SHADOW ONLY - no trading influence.",
        "",
        "Highest crowd temptation:",
    ]

    for x in results[:5]:
        out.append(
            f"{x['symbol']:12} "
            f"tempt={x['temptation']*100:.1f} "
            f"trap={x['trap_risk']*100:.1f} "
            f"squeeze={x['squeeze_score']*100:.1f} "
            f"panic={x['panic_score']*100:.1f} "
            f"| {x['verdict']} "
            f"| cov={x['coverage']}/6"
        )

    out.append("")
    out.append("Highest trap risk:")

    for x in sorted(
        results,
        key=lambda z: z["trap_risk"],
        reverse=True
    )[:5]:

        out.append(
            f"{x['symbol']:12} "
            f"trap={x['trap_risk']*100:.1f} "
            f"tempt={x['temptation']*100:.1f} "
            f"| {x['verdict']}"
        )

    out.append("")
    out.append("Highest panic / exhaustion:")

    for x in sorted(
        results,
        key=lambda z: z["panic_score"],
        reverse=True
    )[:5]:

        out.append(
            f"{x['symbol']:12} "
            f"panic={x['panic_score']*100:.1f} "
            f"| {x['verdict']}"
        )

    with open(
        LATEST_FILE,
        "w",
        encoding="utf-8"
    ) as f:
        f.write("\n".join(out) + "\n")

    print("")
    print("\n".join(out))
    print("")
    print(f"Saved: {LATEST_FILE}")
    print(f"Saved: {CSV_FILE}")


if __name__ == "__main__":
    main()
