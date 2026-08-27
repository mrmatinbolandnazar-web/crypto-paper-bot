#!/usr/bin/env python3
# V5.3 Expert Consensus Shadow Layer - OBSERVATION ONLY.
# Uses V5.2 as the technical engine. Never buys/sells or saves V5.2 state.

import copy
import csv
import json
import math
import os
from datetime import datetime, timezone
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import bot_v5_2 as b

FUTURES_BASE = "https://fapi.binance.com"
CSV_FILE = "expert_shadow_v5_3.csv"
LATEST_FILE = "expert_shadow_v5_3_latest.txt"
PERIOD = "5m"
MAX_CANDIDATES = 8
NEAR_READY_SCORE = 6.50
HTTP_TIMEOUT = 12

WEIGHTS = {
    "top_position": 0.30,
    "top_account": 0.20,
    "taker_flow": 0.20,
    "oi_alignment": 0.15,
    "funding": 0.10,
    "crowd_contrarian": 0.05,
}


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def clamp(value, lo=-1.0, hi=1.0):
    return max(lo, min(hi, value))


def safe_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def futures_get(path, params=None):
    params = params or {}
    url = FUTURES_BASE + path
    if params:
        url += "?" + urlencode(params)
    req = Request(url, headers={"User-Agent": "v5.3-expert-shadow/1.0"})
    with urlopen(req, timeout=HTTP_TIMEOUT) as r:
        return json.loads(r.read().decode("utf-8"))


def get_futures_symbols():
    data = futures_get("/fapi/v1/exchangeInfo")
    out = set()
    for item in data.get("symbols", []):
        if (
            item.get("status") == "TRADING"
            and item.get("quoteAsset") == "USDT"
            and item.get("contractType") == "PERPETUAL"
        ):
            out.add(str(item.get("symbol", "")))
    return out


def latest_ratio(path, symbol):
    rows = futures_get(path, {"symbol": symbol, "period": PERIOD, "limit": 3})
    if not isinstance(rows, list) or not rows:
        return None, None
    latest = safe_float(rows[-1].get("longShortRatio"))
    previous = safe_float(rows[-2].get("longShortRatio")) if len(rows) >= 2 else None
    return latest, previous


def latest_taker_ratio(symbol):
    rows = futures_get(
        "/futures/data/takerlongshortRatio",
        {"symbol": symbol, "period": PERIOD, "limit": 3},
    )
    if not isinstance(rows, list) or not rows:
        return None, None
    latest = safe_float(rows[-1].get("buySellRatio"))
    previous = safe_float(rows[-2].get("buySellRatio")) if len(rows) >= 2 else None
    return latest, previous


def latest_oi_change(symbol):
    rows = futures_get(
        "/futures/data/openInterestHist",
        {"symbol": symbol, "period": PERIOD, "limit": 3},
    )
    if not isinstance(rows, list) or len(rows) < 2:
        return None
    for key in ("sumOpenInterestValue", "sumOpenInterest"):
        previous = safe_float(rows[-2].get(key))
        latest = safe_float(rows[-1].get(key))
        if previous is not None and latest is not None and previous > 0:
            return latest / previous - 1.0
    return None


def latest_funding(symbol):
    data = futures_get("/fapi/v1/premiumIndex", {"symbol": symbol})
    if not isinstance(data, dict):
        return None
    return safe_float(data.get("lastFundingRate"))


def ratio_component(latest, previous=None):
    if latest is None or latest <= 0:
        return None
    level = clamp(math.log(latest, 2))
    if previous is None or previous <= 0:
        return level
    momentum = clamp((latest / previous - 1.0) / 0.10)
    return clamp(level * 0.80 + momentum * 0.20)


def taker_component(latest, previous=None):
    if latest is None or latest <= 0:
        return None
    level = clamp(math.log(latest, 2))
    if previous is None or previous <= 0:
        return level
    momentum = clamp((latest / previous - 1.0) / 0.12)
    return clamp(level * 0.75 + momentum * 0.25)


def oi_alignment_component(oi_change, mom15):
    if oi_change is None or mom15 is None:
        return None
    strength = clamp(abs(oi_change) / 0.025, 0.0, 1.0)
    if abs(mom15) < 0.0002:
        return 0.0
    price_sign = 1.0 if mom15 > 0 else -1.0
    if oi_change > 0:
        return price_sign * strength
    return price_sign * strength * 0.35


def funding_component(rate):
    if rate is None:
        return None
    if abs(rate) <= 0.00010:
        return 0.0
    magnitude = clamp((abs(rate) - 0.00010) / 0.00090, 0.0, 1.0)
    return -magnitude if rate > 0 else magnitude


def weighted_score(components):
    available = [(name, value) for name, value in components.items() if value is not None]
    if not available:
        return 0.0, 0
    weight_sum = sum(WEIGHTS[name] for name, _ in available)
    score = sum(WEIGHTS[name] * value for name, value in available) / weight_sum
    return clamp(score), len(available)


def expert_verdict(score, coverage):
    if coverage < 3:
        return "DATA_WEAK"
    if score >= 0.35:
        return "CONFIRM"
    if score >= 0.10:
        return "SUPPORT"
    if score > -0.10:
        return "NEUTRAL"
    if score > -0.35:
        return "CAUTION"
    return "REJECT"


def expert_snapshot(symbol, analysis):
    top_position, top_position_prev = latest_ratio(
        "/futures/data/topLongShortPositionRatio", symbol
    )
    top_account, top_account_prev = latest_ratio(
        "/futures/data/topLongShortAccountRatio", symbol
    )
    global_ratio, _ = latest_ratio(
        "/futures/data/globalLongShortAccountRatio", symbol
    )
    taker_ratio, taker_prev = latest_taker_ratio(symbol)
    oi_change = latest_oi_change(symbol)
    funding_rate = latest_funding(symbol)

    global_component = ratio_component(global_ratio)
    components = {
        "top_position": ratio_component(top_position, top_position_prev),
        "top_account": ratio_component(top_account, top_account_prev),
        "taker_flow": taker_component(taker_ratio, taker_prev),
        "oi_alignment": oi_alignment_component(oi_change, analysis.get("mom15")),
        "funding": funding_component(funding_rate),
        "crowd_contrarian": None if global_component is None else -global_component,
    }
    score, coverage = weighted_score(components)
    return {
        "expert_score": score,
        "coverage": coverage,
        "verdict": expert_verdict(score, coverage),
        "top_position": top_position,
        "top_account": top_account,
        "global_ratio": global_ratio,
        "taker_ratio": taker_ratio,
        "oi_change": oi_change,
        "funding_rate": funding_rate,
    }


def ensure_csv():
    if os.path.exists(CSV_FILE):
        return
    with open(CSV_FILE, "w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerow([
            "time_utc", "symbol", "source", "regime", "breadth_pct",
            "technical_score", "required_score", "entry_ready", "technical_pass",
            "expert_score", "expert_verdict", "coverage",
            "top_position_ratio", "top_account_ratio", "global_ratio",
            "taker_ratio", "oi_change_pct", "funding_pct", "shadow_action",
        ])


def fmt(value, digits=3):
    if value is None:
        return "NA"
    return f"{value:.{digits}f}"


def main():
    print("=" * 96)
    print("V5.3 EXPERT CONSENSUS SHADOW - OBSERVATION ONLY")
    print("V5.2 remains the technical engine. No V5.2 trade/state is changed.")
    print("=" * 96)

    state = b.load_state()
    shadow_state = copy.deepcopy(state)

    info_map, ticker_map = b.get_market_catalog()
    core_symbols, _, _ = b.build_core_universe(info_map, ticker_map)
    trend_symbols, trend_meta = b.build_trend_watch(set(core_symbols), ticker_map)

    source_map = {symbol: "CORE" for symbol in core_symbols}
    source_map.update({symbol: "TREND" for symbol in trend_symbols})

    analyses = []
    for symbol, source in source_map.items():
        try:
            analyses.append(b.analyze(symbol, source, trend_meta.get(symbol, {})))
        except Exception as exc:
            print(f"{symbol:12} TECH_ERROR {exc}")

    core_set = set(core_symbols)
    core_analyses = [a for a in analyses if a["symbol"] in core_set]
    regime, breadth, regime_reason = b.classify_regime(core_analyses, shadow_state)
    profile = b.risk_profile(regime, int(state.get("loss_streak", 0)))

    if b.in_global_cooldown(state):
        regime = "RISK_OFF"
        regime_reason = "hard_pause"
        profile = b.risk_profile("RISK_OFF", int(state.get("loss_streak", 0)))

    candidates = []
    for analysis in analyses:
        source = analysis.get("source", "CORE")
        entry_ready = (
            analysis.get("trend_entry_ok", False)
            if source == "TREND"
            else analysis.get("core_entry_ok", False)
        )
        required_score = profile["min_score"]
        if source == "TREND":
            required_score += b.CONFIG["trend_score_bonus_required"]

        technical_pass = bool(
            entry_ready
            and analysis["score"] >= required_score
            and profile["max_positions"] > 0
        )
        near_ready = bool(
            entry_ready
            or (
                analysis.get("mtf_checked", False)
                and analysis["score"] >= NEAR_READY_SCORE
            )
        )
        if not near_ready:
            continue

        item = dict(analysis)
        item["_entry_ready"] = entry_ready
        item["_required_score"] = required_score
        item["_technical_pass"] = technical_pass
        candidates.append(item)

    candidates.sort(
        key=lambda x: (
            int(x["_technical_pass"]),
            int(x["_entry_ready"]),
            x["score"],
        ),
        reverse=True,
    )
    candidates = candidates[:MAX_CANDIDATES]

    try:
        futures_symbols = get_futures_symbols()
        futures_catalog_error = None
    except Exception as exc:
        futures_symbols = set()
        futures_catalog_error = str(exc)

    lines = [
        "V5.3 EXPERT SHADOW",
        f"Updated UTC: {now_iso()}",
        (
            f"Regime: {regime} | breadth={breadth*100:.1f}% | "
            f"{regime_reason} | candidates={len(candidates)}"
        ),
        "Mode: SHADOW ONLY - V5.2 buys/sells are unchanged.",
        "",
    ]

    if futures_catalog_error:
        lines.append(f"FUTURES CATALOG ERROR: {futures_catalog_error}")
    if not candidates:
        lines.append("No technical / near-ready candidate this run.")

    ensure_csv()

    for analysis in candidates:
        symbol = analysis["symbol"]

        if symbol not in futures_symbols:
            snap = {
                "expert_score": 0.0,
                "coverage": 0,
                "verdict": "NO_FUTURES_DATA",
                "top_position": None,
                "top_account": None,
                "global_ratio": None,
                "taker_ratio": None,
                "oi_change": None,
                "funding_rate": None,
            }
        else:
            try:
                snap = expert_snapshot(symbol, analysis)
            except Exception as exc:
                print(f"{symbol:12} EXPERT_ERROR {exc}")
                snap = {
                    "expert_score": 0.0,
                    "coverage": 0,
                    "verdict": "DATA_ERROR",
                    "top_position": None,
                    "top_account": None,
                    "global_ratio": None,
                    "taker_ratio": None,
                    "oi_change": None,
                    "funding_rate": None,
                }

        if analysis["_technical_pass"] and snap["verdict"] == "REJECT":
            shadow_action = "WOULD_VETO"
        elif analysis["_technical_pass"] and snap["verdict"] in ("CONFIRM", "SUPPORT"):
            shadow_action = "WOULD_CONFIRM"
        elif analysis["_technical_pass"]:
            shadow_action = "WOULD_HOLD"
        elif snap["verdict"] == "CONFIRM":
            shadow_action = "WOULD_SUPPORT_NEAR_READY"
        else:
            shadow_action = "OBSERVE"

        oi_text = "NA" if snap["oi_change"] is None else f"{snap['oi_change']*100:+.2f}%"
        funding_text = "NA" if snap["funding_rate"] is None else f"{snap['funding_rate']*100:+.4f}%"

        with open(CSV_FILE, "a", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow([
                now_iso(), symbol, analysis.get("source", "CORE"), regime,
                f"{breadth*100:.2f}", f"{analysis['score']:.4f}",
                f"{analysis['_required_score']:.4f}",
                "Y" if analysis["_entry_ready"] else "N",
                "Y" if analysis["_technical_pass"] else "N",
                f"{snap['expert_score']:.4f}", snap["verdict"], snap["coverage"],
                fmt(snap["top_position"], 4), fmt(snap["top_account"], 4),
                fmt(snap["global_ratio"], 4), fmt(snap["taker_ratio"], 4),
                "NA" if snap["oi_change"] is None else f"{snap['oi_change']*100:.4f}",
                "NA" if snap["funding_rate"] is None else f"{snap['funding_rate']*100:.5f}",
                shadow_action,
            ])

        lines.append(
            (
                f"{symbol:12} {analysis.get('source','CORE'):5} "
                f"tech={analysis['score']:.2f}/{analysis['_required_score']:.2f} "
                f"entry={'Y' if analysis['_entry_ready'] else 'N'} "
                f"pass={'Y' if analysis['_technical_pass'] else 'N'} | "
                f"expert={snap['expert_score']:+.2f} {snap['verdict']} "
                f"cov={snap['coverage']}/6 | {shadow_action}"
            )
        )
        lines.append(
            (
                f"  topPos={fmt(snap['top_position'],2)} "
                f"topAcct={fmt(snap['top_account'],2)} "
                f"taker={fmt(snap['taker_ratio'],2)} "
                f"global={fmt(snap['global_ratio'],2)} "
                f"OI5m={oi_text} funding={funding_text}"
            )
        )

    text = "\n".join(lines) + "\n"
    with open(LATEST_FILE, "w", encoding="utf-8") as f:
        f.write(text)

    print("\n" + text)
    print(f"Saved: {CSV_FILE}")
    print(f"Saved: {LATEST_FILE}")


if __name__ == "__main__":
    main()
