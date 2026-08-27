#!/usr/bin/env python3
# Binance Paper Trading Bot V5.2 — SIMULATION ONLY
# 50 guaranteed core USDT spot pairs + separate dynamic trend pool.

import csv
import json
import math
import os
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

BASE_URL = "https://data-api.binance.vision"

CONFIG = {
    "interval": "5m",
    "candle_limit": 180,
    "mtf_15m_limit": 80,
    "mtf_1h_limit": 80,
    "core_max_extension_pct": 0.0080,
    "trend_max_extension_pct": 0.0120,
    "core_max_mom5_chase": 0.0090,
    "trend_max_mom5_chase": 0.0140,
    "core_target_count": 60,
    "trend_scan_count": 20,
    "trend_prefilter_count": 40,
    "api_sleep_seconds": 0.03,

    "market_quote_volume_min": 5_000_000.0,
    "market_deep_scan_count": 60,

    "starting_usdt": 100.0,
    "fee_rate": 0.001,
    "slippage_rate": 0.0003,
    "max_core_spread_pct": 0.0012,
    "max_trend_spread_pct": 0.0018,
    "absolute_max_positions": 1,
    "max_trend_positions": 1,
    "max_new_positions_per_run": 1,

    "ema_fast": 9,
    "ema_slow": 21,
    "rsi_period": 14,
    "atr_period": 14,

    "rsi_min": 49.0,
    "rsi_max": 66.0,
    "momentum_5m_floor": 0.0000,
    "momentum_15m_min": 0.0010,
    "momentum_30m_min": 0.0000,
    "volume_ratio_min": 0.90,

    "trend_24h_change_min": 1.5,
    "trend_24h_change_max": 15.0,
    "trend_quote_volume_min": 10_000_000.0,
    "trend_mom15_min": 0.0050,
    "trend_mom30_min": 0.0080,
    "trend_volume_ratio_min": 1.25,
    "trend_rsi_max": 66.0,
    "trend_score_bonus_required": 0.35,

    "risk_off_breadth": 0.30,
    "weak_breadth": 0.55,
    "strong_breadth": 0.78,
    "hot_recovery_breadth": 0.88,
    "probe_breadth": 0.72,
    "btc_15m_crash_pct": -0.0045,

    "min_stop_pct": 0.0060,
    "max_stop_pct": 0.0140,
    "atr_stop_multiple": 1.35,
    "reward_risk_normal": 1.70,
    "reward_risk_trend": 1.90,
    "min_take_profit_pct": 0.0140,
    "max_take_profit_pct": 0.0350,
    "min_trailing_trigger_pct": 0.0075,
    "min_trailing_distance_pct": 0.0035,
    "min_breakeven_trigger_pct": 0.0065,
    "breakeven_floor_pct": 0.0030,
    "min_hold_minutes_for_trend_exit": 15,
    "max_hold_minutes": 150,
    "stale_profit_ceiling_pct": 0.0020,

    "symbol_cooldown_win_minutes": 20,
    "symbol_cooldown_loss_minutes": 120,
    "loss_streak_hard_pause": 3,
    "global_pause_minutes": 60,
}

STATE_FILE = "paper_state_v5_2.json"
TRADES_FILE = "paper_trades_v5_2.csv"

PRIMARY_CORE_50 = [
    "BTCUSDT","ETHUSDT","BNBUSDT","SOLUSDT","XRPUSDT",
    "DOGEUSDT","ADAUSDT","TRXUSDT","LINKUSDT","AVAXUSDT",
    "SUIUSDT","NEARUSDT","DOTUSDT","LTCUSDT","BCHUSDT",
    "APTUSDT","ARBUSDT","OPUSDT","PEPEUSDT","UNIUSDT",
    "ATOMUSDT","FILUSDT","ETCUSDT","SHIBUSDT","HBARUSDT",
    "XLMUSDT","ICPUSDT","AAVEUSDT","INJUSDT","RUNEUSDT",
    "SEIUSDT","TIAUSDT","FETUSDT","RENDERUSDT","WIFUSDT",
    "BONKUSDT","JUPUSDT","ALGOUSDT","VETUSDT","POLUSDT",
    "CAKEUSDT","ONDOUSDT","TAOUSDT","ENAUSDT","PENDLEUSDT",
    "WLDUSDT","STXUSDT","GRTUSDT","IMXUSDT","LDOUSDT",
]

RESERVE_PRIORITY = [
    "PYTHUSDT","JASMYUSDT","SANDUSDT","MANAUSDT","CHZUSDT",
    "CRVUSDT","COMPUSDT","GALAUSDT","THETAUSDT","ZECUSDT",
    "DASHUSDT","EGLDUSDT","1INCHUSDT","FLOWUSDT","ARUSDT",
    "SKYUSDT","ORDIUSDT","NOTUSDT","STRKUSDT",
]

EXCLUDED_BASE_ASSETS = {
    "USDT","USDC","FDUSD","TUSD","USDP","DAI","EUR","AEUR",
    "BUSD","USTC","WBTC","BTCB","ETHW","USD1","RLUSD","EURI","U","XAUT","PAXG",
}
LEVERAGED_SUFFIXES = ("UP", "DOWN", "BULL", "BEAR")


def now_dt():
    return datetime.now(timezone.utc)


def now_iso():
    return now_dt().isoformat()


def parse_iso(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def clamp(value, lo, hi):
    return max(lo, min(hi, value))


def http_get(path, params=None):
    params = params or {}
    url = BASE_URL + path
    if params:
        url += "?" + urlencode(params)
    req = Request(url, headers={"User-Agent": "paper-bot-v5.2/1.0"})
    with urlopen(req, timeout=25) as r:
        return json.loads(r.read().decode("utf-8"))


def eligible_spot_symbol(info):
    base = str(info.get("baseAsset", ""))
    symbol = str(info.get("symbol", ""))
    if not (
        info.get("status") == "TRADING"
        and info.get("quoteAsset") == "USDT"
        and info.get("isSpotTradingAllowed") is not False
    ):
        return False
    if base in EXCLUDED_BASE_ASSETS:
        return False
    if any(base.endswith(s) for s in LEVERAGED_SUFFIXES):
        return False
    if any(symbol.endswith(s + "USDT") for s in LEVERAGED_SUFFIXES):
        return False
    return True


def get_market_catalog():
    exchange = http_get("/api/v3/exchangeInfo")
    tickers = http_get("/api/v3/ticker/24hr")
    info_map = {
        x.get("symbol"): x for x in exchange.get("symbols", [])
        if eligible_spot_symbol(x)
    }
    ticker_map = {}
    for t in tickers:
        symbol = t.get("symbol")
        if symbol not in info_map:
            continue
        try:
            ticker_map[symbol] = {
                "quote_volume": float(t.get("quoteVolume", 0.0) or 0.0),
                "change_pct": float(t.get("priceChangePercent", 0.0) or 0.0),
                "last_price": float(t.get("lastPrice", 0.0) or 0.0),
            }
        except (TypeError, ValueError):
            continue
    return info_map, ticker_map



def build_core_universe(info_map, ticker_map):
    mandatory = ["BTCUSDT", "ETHUSDT"]

    liquid = []

    for symbol in info_map:
        t = ticker_map.get(symbol)
        if not t:
            continue

        qv = float(t.get("quote_volume", 0.0) or 0.0)

        if qv < CONFIG["market_quote_volume_min"]:
            continue

        liquid.append(
            (
                qv,
                abs(float(t.get("change_pct", 0.0) or 0.0)),
                symbol,
            )
        )

    liquid.sort(reverse=True)

    chosen = []

    for symbol in mandatory:
        if symbol in info_map and symbol in ticker_map:
            chosen.append(symbol)

    for qv, chg, symbol in liquid:
        if symbol in chosen:
            continue

        chosen.append(symbol)

        if len(chosen) >= CONFIG["market_deep_scan_count"]:
            break

    if len(chosen) < 20:
        raise RuntimeError(
            f"Only {len(chosen)} sufficiently liquid USDT spot pairs available."
        )

    return chosen, [], []


def build_trend_watch(core_symbols, ticker_map):
    ranked = []

    for symbol, t in ticker_map.items():
        qv = float(t.get("quote_volume", 0.0) or 0.0)
        chg = float(t.get("change_pct", 0.0) or 0.0)

        if qv < CONFIG["trend_quote_volume_min"]:
            continue

        if not (
            CONFIG["trend_24h_change_min"]
            <= chg
            <= CONFIG["trend_24h_change_max"]
        ):
            continue

        liquidity_score = math.log10(max(qv, 1.0))
        change_score = chg

        rank = (
            change_score
            + 0.45 * liquidity_score
        )

        ranked.append(
            (
                rank,
                qv,
                chg,
                symbol,
            )
        )

    ranked.sort(reverse=True)

    top = ranked[:CONFIG["trend_prefilter_count"]]

    symbols = [
        x[3]
        for x in top[:CONFIG["trend_scan_count"]]
    ]

    meta = {
        x[3]: {
            "quote_volume": x[1],
            "change_pct": x[2],
        }
        for x in top
    }

    return symbols, meta

def get_spread_pct(symbol):
    x=http_get("/api/v3/ticker/bookTicker", {"symbol": symbol})
    bid=float(x.get("bidPrice",0) or 0)
    ask=float(x.get("askPrice",0) or 0)

    if bid <= 0 or ask <= 0 or ask < bid:
        return 999.0

    mid=(bid+ask)/2.0
    return (ask-bid)/mid


def get_bars(symbol, interval=None, limit=None):
    interval = interval or CONFIG["interval"]
    limit = limit or CONFIG["candle_limit"]

    data = http_get("/api/v3/klines", {
        "symbol": symbol,
        "interval": interval,
        "limit": limit,
    })
    bars = [{
        "open_time": int(x[0]), "open": float(x[1]), "high": float(x[2]),
        "low": float(x[3]), "close": float(x[4]), "volume": float(x[5]),
        "close_time": int(x[6]),
    } for x in data]
    if len(bars) >= 2:
        bars = bars[:-1]
    return bars


def ema(values, period):
    if len(values) < period:
        return None
    out = sum(values[:period]) / period
    k = 2 / (period + 1)
    for v in values[period:]:
        out = v * k + out * (1 - k)
    return out


def rsi(values, period):
    if len(values) < period + 1:
        return None
    gains, losses = [], []
    for i in range(-period, 0):
        d = values[i] - values[i - 1]
        gains.append(max(d, 0.0))
        losses.append(max(-d, 0.0))
    ag = sum(gains) / period
    al = sum(losses) / period
    if al == 0:
        return 100.0
    rs = ag / al
    return 100.0 - 100.0 / (1.0 + rs)


def atr_pct(bars, period):
    if len(bars) < period + 1:
        return None
    trs = []
    for i in range(-period, 0):
        b = bars[i]
        prev_close = bars[i - 1]["close"]
        trs.append(max(
            b["high"] - b["low"],
            abs(b["high"] - prev_close),
            abs(b["low"] - prev_close),
        ))
    price = bars[-1]["close"]
    return (sum(trs) / len(trs)) / price if price > 0 else None


def default_state():
    return {
        "cash_usdt": CONFIG["starting_usdt"], "positions": {},
        "realized_pnl_usdt": 0.0, "total_fees_usdt": 0.0,
        "wins": 0, "losses": 0, "loss_streak": 0,
        "cooldown_until": None, "symbol_cooldowns": {},
        "sum_win_pnl": 0.0, "sum_loss_pnl": 0.0,
        "peak_equity": CONFIG["starting_usdt"], "max_drawdown_pct": 0.0,
        "recovery_confirm_runs": 0, "last_regime": None,
        "started_at": now_iso(),
    }


def normalize_state(state):
    for k, v in default_state().items():
        state.setdefault(k, v)
    return state


def load_state():
    if not os.path.exists(STATE_FILE):
        return default_state()
    with open(STATE_FILE, "r", encoding="utf-8") as f:
        return normalize_state(json.load(f))


def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def ensure_trade_csv():
    if not os.path.exists(TRADES_FILE):
        with open(TRADES_FILE, "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow([
                "time_utc","symbol","side","source","price","qty",
                "gross_usdt","fee_usdt","realized_pnl_usdt","score",
                "stop_pct","take_profit_pct","reason",
            ])


def log_trade(symbol, side, source, price, qty, gross, fee, pnl, score,
              stop_pct, take_profit_pct, reason):
    ensure_trade_csv()
    with open(TRADES_FILE, "a", newline="", encoding="utf-8") as f:
        csv.writer(f).writerow([
            now_iso(), symbol, side, source, f"{price:.10f}", f"{qty:.10f}",
            f"{gross:.6f}", f"{fee:.6f}", f"{pnl:.6f}", f"{score:.3f}",
            f"{stop_pct:.6f}", f"{take_profit_pct:.6f}", reason,
        ])


def in_global_cooldown(state):
    until = parse_iso(state.get("cooldown_until"))
    return bool(until and now_dt() < until)


def symbol_in_cooldown(state, symbol):
    until = parse_iso(state.get("symbol_cooldowns", {}).get(symbol))
    return bool(until and now_dt() < until)


def cleanup_cooldowns(state):
    now = now_dt()
    state["symbol_cooldowns"] = {
        s: ts for s, ts in state.get("symbol_cooldowns", {}).items()
        if parse_iso(ts) and parse_iso(ts) > now
    }
    until = parse_iso(state.get("cooldown_until"))
    if until and until <= now:
        state["cooldown_until"] = None


def higher_tf_snapshot(symbol, interval, limit):
    bars = get_bars(symbol, interval, limit)

    if len(bars) < 30:
        raise ValueError("not enough higher-timeframe candles")

    closes = [b["close"] for b in bars]
    price = closes[-1]

    ef = ema(closes, CONFIG["ema_fast"])
    es = ema(closes, CONFIG["ema_slow"])
    ef_prev = ema(closes[:-1], CONFIG["ema_fast"])
    rr = rsi(closes, CONFIG["rsi_period"])

    if None in (ef, es, ef_prev, rr):
        raise ValueError("not enough higher-timeframe indicator data")

    mom1 = price / closes[-2] - 1.0
    mom3 = price / closes[-4] - 1.0
    fast_slope = ef / ef_prev - 1.0 if ef_prev else 0.0

    return {
        "price": price,
        "ema_fast": ef,
        "ema_slow": es,
        "fast_slope": fast_slope,
        "rsi": rr,
        "mom1": mom1,
        "mom3": mom3,
    }


def analyze(symbol, source="CORE", trend_meta=None):
    bars = get_bars(symbol)
    if len(bars) < 40:
        raise ValueError("not enough closed candles")

    closes = [b["close"] for b in bars]
    vols = [b["volume"] for b in bars]
    last = bars[-1]
    price = closes[-1]

    ef = ema(closes, CONFIG["ema_fast"])
    es = ema(closes, CONFIG["ema_slow"])
    ef_prev = ema(closes[:-1], CONFIG["ema_fast"])
    es_prev = ema(closes[:-1], CONFIG["ema_slow"])
    rr = rsi(closes, CONFIG["rsi_period"])
    atr = atr_pct(bars, CONFIG["atr_period"])
    if None in (ef, es, ef_prev, es_prev, rr, atr):
        raise ValueError("not enough indicator data")

    mom5 = price / closes[-2] - 1.0
    mom15 = price / closes[-4] - 1.0
    mom30 = price / closes[-7] - 1.0
    prev_vols = vols[-21:-1]
    avg_vol = sum(prev_vols) / len(prev_vols) if prev_vols else 0.0
    vol_ratio = vols[-1] / avg_vol if avg_vol > 0 else 0.0
    trend_gap = ef / es - 1.0 if es else 0.0
    fast_slope = ef / ef_prev - 1.0 if ef_prev else 0.0
    slow_slope = es / es_prev - 1.0 if es_prev else 0.0

    extension_pct = price / ef - 1.0 if ef else 0.0

    preliminary_strength = (
        price > ef > es
        and fast_slope > 0
        and 47.0 <= rr <= 68.0
        and mom5 >= 0
        and mom15 > 0
    )

    must_check_mtf = (
        symbol in ("BTCUSDT", "ETHUSDT")
        or preliminary_strength
        or source == "TREND"
    )

    tf15_ok = False
    tf1h_ok = False
    tf15 = None
    tf1h = None

    if must_check_mtf:
        try:
            tf15 = higher_tf_snapshot(
                symbol,
                "15m",
                CONFIG["mtf_15m_limit"],
            )

            tf1h = higher_tf_snapshot(
                symbol,
                "1h",
                CONFIG["mtf_1h_limit"],
            )

            tf15_ok = (
                tf15["price"] > tf15["ema_fast"] > tf15["ema_slow"]
                and tf15["fast_slope"] > 0
                and 47.0 <= tf15["rsi"] <= 72.0
                and tf15["mom1"] >= 0
                and tf15["mom3"] >= 0.0005
            )

            tf1h_ok = (
                tf1h["price"] > tf1h["ema_fast"] > tf1h["ema_slow"]
                and tf1h["fast_slope"] > 0
                and 48.0 <= tf1h["rsi"] <= 67.0
                and tf1h["mom1"] >= 0
                and tf1h["mom3"] >= 0.0020
            )

        except Exception:
            tf15_ok = False
            tf1h_ok = False

    if source == "TREND":
        max_extension = CONFIG["trend_max_extension_pct"]
        max_mom5_chase = CONFIG["trend_max_mom5_chase"]
    else:
        max_extension = CONFIG["core_max_extension_pct"]
        max_mom5_chase = CONFIG["core_max_mom5_chase"]

    chase_ok = (
        extension_pct <= max_extension
        and mom5 <= max_mom5_chase
    )

    spread_pct = 999.0
    spread_limit = (
        CONFIG["max_trend_spread_pct"]
        if source == "TREND"
        else CONFIG["max_core_spread_pct"]
    )

    if must_check_mtf:
        try:
            spread_pct = get_spread_pct(symbol)
        except Exception:
            spread_pct = 999.0

    spread_ok = spread_pct <= spread_limit

    mtf_ok = tf15_ok and tf1h_ok and chase_ok and spread_ok

    score, reasons = 0.0, []
    if price > ef > es:
        score += 1.40; reasons.append("trend")
    if fast_slope > 0 and slow_slope >= -0.00025:
        score += 0.80; reasons.append("slope")
    if 50.0 <= rr <= 62.0:
        score += 1.00; reasons.append("rsi")
    elif CONFIG["rsi_min"] <= rr <= CONFIG["rsi_max"]:
        score += 0.60; reasons.append("rsi_ok")
    if mom5 >= 0.0003:
        score += 0.80; reasons.append("mom5")
    elif mom5 >= CONFIG["momentum_5m_floor"]:
        score += 0.25; reasons.append("mom5_hold")
    if mom15 >= CONFIG["momentum_15m_min"]:
        score += 1.00; reasons.append("mom15")
    if mom30 >= 0:
        score += 0.50; reasons.append("mom30")
    elif mom30 >= CONFIG["momentum_30m_min"]:
        score += 0.20; reasons.append("mom30_hold")
    if vol_ratio >= 1.10:
        score += min(1.10, 0.90 + (vol_ratio - 1.10) * 0.25); reasons.append("volume")
    elif vol_ratio >= CONFIG["volume_ratio_min"]:
        score += 0.50; reasons.append("volume_ok")
    if 0.0004 <= trend_gap <= 0.010:
        score += 0.35; reasons.append("gap")
    if mom5 > 0.018 or rr > 72.0:
        score -= 1.35; reasons.append("hot_penalty")
    elif rr > CONFIG["rsi_max"]:
        score -= 0.75; reasons.append("warm_penalty")

    quality_bonus = 0.0
    quality_bonus += 0.35 * clamp((mom15 - 0.0020) / 0.0080, 0.0, 1.0)
    quality_bonus += 0.20 * clamp(mom30 / 0.0120, 0.0, 1.0)
    quality_bonus += 0.30 * clamp((vol_ratio - 0.90) / 1.10, 0.0, 1.0)
    quality_bonus += 0.20 * clamp(fast_slope / 0.0015, 0.0, 1.0)

    if rr > 64.0:
        quality_bonus -= min(0.35, (rr - 64.0) * 0.08)
    if mom5 > 0.012:
        quality_bonus -= min(0.45, (mom5 - 0.012) * 18.0)

    score += quality_bonus

    core_entry_ok = (
        price > ef > es and fast_slope > 0
        and CONFIG["rsi_min"] <= rr <= CONFIG["rsi_max"]
        and mom5 >= CONFIG["momentum_5m_floor"]
        and mom15 >= CONFIG["momentum_15m_min"]
        and mom30 >= CONFIG["momentum_30m_min"]
        and vol_ratio >= CONFIG["volume_ratio_min"]
        and mtf_ok
    )

    trend_24h = (trend_meta or {}).get("change_pct", 0.0)
    trend_entry_ok = (
        source == "TREND" and price > ef > es and fast_slope > 0
        and 50.0 <= rr <= CONFIG["trend_rsi_max"]
        and mom5 >= 0.0003
        and mom15 >= CONFIG["trend_mom15_min"]
        and mom30 >= CONFIG["trend_mom30_min"]
        and vol_ratio >= CONFIG["trend_volume_ratio_min"]
        and CONFIG["trend_24h_change_min"] <= trend_24h <= CONFIG["trend_24h_change_max"]
        and mtf_ok
    )

    return {
        "symbol": symbol, "source": source, "price": price,
        "high": last["high"], "low": last["low"],
        "ema_fast": ef, "ema_slow": es, "fast_slope": fast_slope,
        "slow_slope": slow_slope, "rsi": rr, "mom5": mom5,
        "mom15": mom15, "mom30": mom30, "vol_ratio": vol_ratio,
        "atr_pct": atr, "score": score,
        "core_entry_ok": core_entry_ok,
        "tf15_ok": tf15_ok,
        "tf1h_ok": tf1h_ok,
        "mtf_checked": must_check_mtf,
        "mtf_ok": mtf_ok,
        "chase_ok": chase_ok,
        "spread_ok": spread_ok,
        "spread_pct": spread_pct,
        "extension_pct": extension_pct,
        "reject_reason": (
            "PRECHECK"
            if not must_check_mtf
            else "TF15"
            if not tf15_ok
            else "TF1H"
            if not tf1h_ok
            else "CHASE"
            if not chase_ok
            else "SPREAD"
            if not spread_ok
            else "ENTRY_RULES"
        ),
        "trend_entry_ok": trend_entry_ok, "trend_24h_change": trend_24h,
        "reason": "+".join(reasons) if reasons else "weak",
    }



def choose_exit_params(a, source):
    stop_pct = clamp(
        a["atr_pct"] * CONFIG["atr_stop_multiple"],
        CONFIG["min_stop_pct"], CONFIG["max_stop_pct"],
    )

    rr = (
        CONFIG["reward_risk_trend"]
        if source == "TREND"
        else CONFIG["reward_risk_normal"]
    )

    fee_factor = (1.0 - CONFIG["fee_rate"]) ** 2
    net_risk = 1.0 - fee_factor * (1.0 - stop_pct)

    fee_aware_tp = (1.0 + rr * net_risk) / fee_factor - 1.0

    tp_pct = clamp(
        max(CONFIG["min_take_profit_pct"], fee_aware_tp),
        CONFIG["min_take_profit_pct"],
        CONFIG["max_take_profit_pct"],
    )

    trail_trigger = max(
        CONFIG["min_trailing_trigger_pct"],
        tp_pct * 0.65,
    )
    trail_distance = max(
        CONFIG["min_trailing_distance_pct"],
        stop_pct * 0.60,
    )
    be_trigger = max(
        CONFIG["min_breakeven_trigger_pct"],
        stop_pct,
    )

    return stop_pct, tp_pct, trail_trigger, trail_distance, be_trigger

def buy(state, a, spend_usdt, reason):
    symbol, source = a["symbol"], a["source"]
    if symbol in state["positions"] or symbol_in_cooldown(state, symbol):
        return False
    if in_global_cooldown(state):
        return False
    if len(state["positions"]) >= CONFIG["absolute_max_positions"]:
        return False
    trend_open = sum(1 for p in state["positions"].values() if p.get("source") == "TREND")
    if source == "TREND" and trend_open >= CONFIG["max_trend_positions"]:
        return False

    spend = min(spend_usdt, state["cash_usdt"])
    if spend < 1.0:
        return False

    stop_pct, tp_pct, trail_trigger, trail_distance, be_trigger = choose_exit_params(a, source)
    exec_price = a["price"] * (1.0 + CONFIG["slippage_rate"])
    fee = spend * CONFIG["fee_rate"]
    qty = (spend - fee) / exec_price
    state["cash_usdt"] -= spend
    state["total_fees_usdt"] += fee
    state["positions"][symbol] = {
        "source": source, "entry_price": exec_price, "qty": qty,
        "cost_usdt": spend, "entry_fee_usdt": fee, "peak_price": exec_price,
        "entry_score": a["score"], "opened_at": now_iso(),
        "stop_pct": stop_pct, "take_profit_pct": tp_pct,
        "trailing_trigger_pct": trail_trigger,
        "trailing_distance_pct": trail_distance,
        "breakeven_trigger_pct": be_trigger,
    }
    log_trade(symbol, "BUY", source, exec_price, qty, spend, fee, 0.0,
              a["score"], stop_pct, tp_pct, reason)
    print(
        f">>> BUY {symbol} [{source}] @ {exec_price:.8f} | ${spend:.2f} paper | "
        f"score={a['score']:.2f} | SL={stop_pct*100:.2f}% TP={tp_pct*100:.2f}% | {reason}"
    )
    return True


def sell(state, symbol, price, reason):
    pos = state["positions"].get(symbol)
    if not pos:
        return None
    exec_price = price * (1.0 - CONFIG["slippage_rate"])
    gross = pos["qty"] * exec_price
    exit_fee = gross * CONFIG["fee_rate"]
    net = gross - exit_fee
    pnl = net - pos["cost_usdt"]
    state["cash_usdt"] += net
    state["realized_pnl_usdt"] += pnl
    state["total_fees_usdt"] += exit_fee

    if pnl >= 0:
        state["wins"] += 1
        state["loss_streak"] = 0
        state["sum_win_pnl"] += pnl
        cooldown_min = CONFIG["symbol_cooldown_win_minutes"]
    else:
        state["losses"] += 1
        state["loss_streak"] = int(state.get("loss_streak", 0)) + 1
        state["sum_loss_pnl"] += pnl
        cooldown_min = CONFIG["symbol_cooldown_loss_minutes"]
        if state["loss_streak"] >= CONFIG["loss_streak_hard_pause"]:
            state["cooldown_until"] = (
                now_dt() + timedelta(minutes=CONFIG["global_pause_minutes"])
            ).isoformat()
            print(f"!!! HARD PAUSE {CONFIG['global_pause_minutes']}m after loss streak={state['loss_streak']}")

    state.setdefault("symbol_cooldowns", {})[symbol] = (
        now_dt() + timedelta(minutes=cooldown_min)
    ).isoformat()
    log_trade(
        symbol, "SELL", pos.get("source", "CORE"), exec_price, pos["qty"], gross,
        exit_fee, pnl, pos.get("entry_score", 0.0), pos.get("stop_pct", 0.0),
        pos.get("take_profit_pct", 0.0), reason,
    )
    del state["positions"][symbol]
    print(f"<<< SELL {symbol} @ {exec_price:.8f} | P/L ${pnl:+.4f} | {reason}")
    return pnl


def position_age_minutes(pos):
    opened = parse_iso(pos.get("opened_at"))
    if not opened:
        return 0.0
    return max(0.0, (now_dt() - opened).total_seconds() / 60.0)


def manage_open_position(state, a):
    symbol = a["symbol"]
    pos = state["positions"].get(symbol)
    if not pos:
        return

    entry = pos["entry_price"]
    close, candle_high, candle_low = a["price"], a["high"], a["low"]
    previous_peak = max(pos.get("peak_price", entry), entry)
    stop_pct = pos.get("stop_pct", CONFIG["min_stop_pct"])
    tp_pct = pos.get("take_profit_pct", CONFIG["min_take_profit_pct"])
    hard_stop = entry * (1.0 - stop_pct)
    take_profit = entry * (1.0 + tp_pct)

    if candle_low <= hard_stop:
        sell(state, symbol, hard_stop, "ATR_HARD_STOP"); return
    if candle_high >= take_profit:
        sell(state, symbol, take_profit, "ATR_TAKE_PROFIT"); return

    peak_change = previous_peak / entry - 1.0
    if peak_change >= pos.get("trailing_trigger_pct", 0.008):
        trail = previous_peak * (1.0 - pos.get("trailing_distance_pct", 0.004))
        if candle_low <= trail:
            sell(state, symbol, trail, "TRAILING_STOP"); return
    if peak_change >= pos.get("breakeven_trigger_pct", 0.007):
        floor = entry * (1.0 + CONFIG["breakeven_floor_pct"])
        if candle_low <= floor:
            sell(state, symbol, floor, "PROTECT_PROFIT"); return

    pos["peak_price"] = max(previous_peak, candle_high, close)
    age = position_age_minutes(pos)
    change = close / entry - 1.0
    if age >= CONFIG["min_hold_minutes_for_trend_exit"] and a["ema_fast"] < a["ema_slow"] and a["mom15"] < 0:
        sell(state, symbol, close, "CONFIRMED_TREND_LOST"); return
    if age >= CONFIG["max_hold_minutes"] and change < CONFIG["stale_profit_ceiling_pct"] and a["mom15"] <= 0:
        sell(state, symbol, close, "TIME_EXIT")


def portfolio_value(state, price_map):
    total = state["cash_usdt"]
    for symbol, pos in state["positions"].items():
        total += pos["qty"] * price_map.get(symbol, pos["entry_price"])
    return total



def classify_regime(core_analyses, state=None):
    if not core_analyses:
        return "RISK_OFF", 0.0, "no_data"

    positive = 0
    for a in core_analyses:
        votes = (
            int(a["ema_fast"] > a["ema_slow"])
            + int(a["mom15"] > 0)
            + int(a["mom30"] > 0)
        )
        if votes >= 2:
            positive += 1

    breadth = positive / len(core_analyses)

    btc = next(
        (a for a in core_analyses if a["symbol"] == "BTCUSDT"),
        None,
    )
    eth = next(
        (a for a in core_analyses if a["symbol"] == "ETHUSDT"),
        None,
    )

    if btc and btc["mom15"] <= CONFIG["btc_15m_crash_pct"]:
        raw_regime = "RISK_OFF"
        reason = "btc_fast_drop"

    elif breadth < CONFIG["risk_off_breadth"]:
        raw_regime = "RISK_OFF"
        reason = "breadth_risk_off"

    elif btc and eth and btc["mom15"] <= 0 and eth["mom15"] <= 0:
        raw_regime = "RISK_OFF"
        reason = "btc_eth_15m_soft"

    elif breadth < CONFIG["weak_breadth"]:
        raw_regime = "WEAK"
        reason = "breadth_weak"

    else:
        hot_recovery_ok = bool(
            breadth >= CONFIG["hot_recovery_breadth"]
            and btc
            and eth
            and btc["mom15"] > 0
            and eth["mom15"] > 0
            and btc.get("tf15_ok", False)
            and eth.get("tf15_ok", False)
        )

        btc_ok = bool(
            btc
            and btc["ema_fast"] > btc["ema_slow"]
            and btc["mom15"] > 0
            and btc["mom30"] > 0
            and btc.get("tf15_ok", False)
            and btc.get("tf1h_ok", False)
        )

        eth_ok = bool(
            eth
            and eth["ema_fast"] > eth["ema_slow"]
            and eth["mom15"] > 0
            and eth["mom30"] > 0
            and eth.get("tf15_ok", False)
            and eth.get("tf1h_ok", False)
        )

        if breadth >= CONFIG["strong_breadth"] and btc_ok and eth_ok:
            raw_regime = "STRONG"
            reason = "broad_strength_btc_eth_confirmed"
        elif hot_recovery_ok:
            raw_regime = "HOT_RECOVERY"
            reason = "hot_breadth_15m_confirmed"
        elif not btc_ok:
            if breadth >= CONFIG["probe_breadth"]:
                raw_regime = "PROBE"
                reason = "broad_market_probe_btc_unconfirmed"
            else:
                raw_regime = "WEAK"
                reason = "btc_not_confirmed"
        else:
            raw_regime = "NORMAL"
            reason = "market_normal"

    if state is not None:
        if raw_regime == "HOT_RECOVERY":
            state["recovery_confirm_runs"] = 0
            state["last_regime"] = "HOT_RECOVERY"
            return raw_regime, breadth, reason

        if raw_regime == "RISK_OFF":
            state["recovery_confirm_runs"] = 0
            state["last_regime"] = "RISK_OFF"
            return raw_regime, breadth, reason

        recovery_count = int(state.get("recovery_confirm_runs", 0))

        if state.get("last_regime") == "RISK_OFF" or recovery_count > 0:
            recovery_count += 1
            state["recovery_confirm_runs"] = recovery_count
            state["last_regime"] = raw_regime

            if recovery_count < 2:
                return (
                    "RISK_OFF",
                    breadth,
                    f"recovery_confirm_{recovery_count}of2",
                )

            state["recovery_confirm_runs"] = 0

        state["last_regime"] = raw_regime

    return raw_regime, breadth, reason


def risk_profile(regime, loss_streak):
    profiles = {
        "RISK_OFF": {
            "max_positions": 0,
            "min_score": 99.0,
            "size_fraction": 0.0,
        },
        "WEAK": {
            "max_positions": 0,
            "min_score": 99.0,
            "size_fraction": 0.0,
        },
        "PROBE": {
            "max_positions": 1,
            "min_score": 7.70,
            "size_fraction": 0.02,
        },
        "HOT_RECOVERY": {
            "max_positions": 1,
            "min_score": 7.50,
            "size_fraction": 0.03,
        },
        "NORMAL": {
            "max_positions": 1,
            "min_score": 7.15,
            "size_fraction": 0.04,
        },
        "STRONG": {
            "max_positions": 1,
            "min_score": 6.95,
            "size_fraction": 0.06,
        },
    }

    p = dict(profiles[regime])

    if regime == "RISK_OFF":
        return p

    if loss_streak >= 3:
        if regime == "STRONG":
            return {
                "max_positions": 1,
                "min_score": 7.60,
                "size_fraction": 0.025,
            }
        return {
            "max_positions": 0,
            "min_score": 99.0,
            "size_fraction": 0.0,
        }

    if loss_streak == 2:
        p["min_score"] += 0.50
        p["size_fraction"] *= 0.50
        p["max_positions"] = min(p["max_positions"], 1)

    elif loss_streak == 1:
        p["min_score"] += 0.25
        p["size_fraction"] *= 0.70
        p["max_positions"] = min(p["max_positions"], 1)

    p["max_positions"] = min(
        p["max_positions"],
        CONFIG["absolute_max_positions"],
    )

    return p

def update_drawdown(state, equity):
    state["peak_equity"] = max(float(state.get("peak_equity", equity)), equity)
    peak = state["peak_equity"]
    dd = (peak - equity) / peak if peak > 0 else 0.0
    state["max_drawdown_pct"] = max(float(state.get("max_drawdown_pct", 0.0)), dd)


def main():
    print("=" * 96)
    print("BINANCE PAPER TRADING BOT V5.2 — GITHUB ACTIONS — SIMULATION ONLY")
    print("50 guaranteed core pairs + dynamic trend pool | adaptive regime | dynamic risk | no real orders")
    print("=" * 96)

    state = load_state()
    cleanup_cooldowns(state)
    ensure_trade_csv()

    info_map, ticker_map = get_market_catalog()
    core_symbols, missing, replacements = build_core_universe(info_map, ticker_map)
    trend_symbols, trend_meta = build_trend_watch(set(core_symbols), ticker_map)

    print(f"Full USDT market discovered: {len(ticker_map)} eligible ticker records")
    print(f"Dynamic liquid deep-scan universe: {len(core_symbols)}")
    if missing:
        print("Unavailable priority names: " + ", ".join(missing))
    if replacements:
        print("Automatic liquid replacements: " + ", ".join(replacements))
    print("LIQUID SCAN: " + ", ".join(core_symbols))
    print(f"Trend watch: {len(trend_symbols)}")
    print("TREND: " + (", ".join(trend_symbols) if trend_symbols else "none"))

    source_map = {s: "CORE" for s in core_symbols}
    source_map.update({s: "TREND" for s in trend_symbols})
    for symbol, pos in state["positions"].items():
        source_map.setdefault(symbol, pos.get("source", "CORE"))

    analyses, prices = [], {}
    print(f"\n[{now_iso()}]")
    for symbol, source in source_map.items():
        try:
            a = analyze(symbol, source, trend_meta.get(symbol, {}))
            analyses.append(a)
            prices[symbol] = a["price"]
            manage_open_position(state, a)
            entry_flag = a["trend_entry_ok"] if source == "TREND" else a["core_entry_ok"]
            trend_suffix = f" 24h={a['trend_24h_change']:+.1f}%" if source == "TREND" else ""
            print(
                f"{symbol:12} {source:5} p={a['price']:.8f} RSI={a['rsi']:5.1f} "
                f"M5={a['mom5']*100:+.2f}% M15={a['mom15']*100:+.2f}% "
                f"VOLx={a['vol_ratio']:.2f} ATR={a['atr_pct']*100:.2f}% "
                f"TF15={'Y' if a.get('tf15_ok') else 'N'} "
                f"TF1H={'Y' if a.get('tf1h_ok') else 'N'} "
                f"EXT={a.get('extension_pct',0)*100:+.2f}% "
                f"SCORE={a['score']:.2f} ENTRY={'Y' if entry_flag else 'N'}{trend_suffix}"
            )
            time.sleep(CONFIG["api_sleep_seconds"])
        except (HTTPError, URLError, TimeoutError, ValueError) as e:
            print(f"{symbol:12} DATA ERROR: {e}")
        except Exception as e:
            print(f"{symbol:12} ERROR: {e}")

    core_set = set(core_symbols)
    core_analyses = [a for a in analyses if a["symbol"] in core_set]
    regime, breadth, regime_reason = classify_regime(core_analyses, state)
    profile = risk_profile(regime, int(state.get("loss_streak", 0)))

    if in_global_cooldown(state):
        regime = "RISK_OFF"
        profile = risk_profile("RISK_OFF", int(state.get("loss_streak", 0)))
        regime_reason = f"hard_pause_until_{state.get('cooldown_until')}"

    print(
        f"\nMarket regime: {regime} | breadth={breadth*100:.1f}% | {regime_reason} | "
        f"max_pos={profile['max_positions']} | min_score={profile['min_score']:.2f} | "
        f"size={profile['size_fraction']*100:.1f}% equity"
    )

    # Entry rejection diagnostics
    diag_counts = {
        "PRECHECK": 0,
        "TF15": 0,
        "TF1H": 0,
        "CHASE": 0,
        "SPREAD": 0,
        "ENTRY_RULES": 0,
    }

    source_stats = {
        "CORE": {"total": 0, "entry_ready": 0, "score_ready": 0, "fully_ready": 0},
        "TREND": {"total": 0, "entry_ready": 0, "score_ready": 0, "fully_ready": 0},
    }

    near_misses = []

    for a in analyses:
        source = a.get("source", "CORE")
        if source not in source_stats:
            continue

        source_stats[source]["total"] += 1

        entry_ready = (
            a["trend_entry_ok"]
            if source == "TREND"
            else a["core_entry_ok"]
        )

        required_score = profile["min_score"]
        if source == "TREND":
            required_score += CONFIG["trend_score_bonus_required"]

        score_ready = a["score"] >= required_score

        if entry_ready:
            source_stats[source]["entry_ready"] += 1
        if score_ready:
            source_stats[source]["score_ready"] += 1
        if entry_ready and score_ready:
            source_stats[source]["fully_ready"] += 1

        if not entry_ready:
            reason = a.get("reject_reason", "ENTRY_RULES")
            if reason in diag_counts:
                diag_counts[reason] += 1

            near_misses.append({
                "symbol": a["symbol"],
                "source": source,
                "score": a["score"],
                "required_score": required_score,
                "reject_reason": reason,
                "tf15": a.get("tf15_ok", False),
                "tf1h": a.get("tf1h_ok", False),
                "chase": a.get("chase_ok", False),
                "spread": a.get("spread_ok", False),
            })

    print("\nREJECTION DIAGNOSTICS:")
    print(
        "Reject totals | "
        f"PRECHECK={diag_counts['PRECHECK']} | "
        f"TF15={diag_counts['TF15']} | "
        f"TF1H={diag_counts['TF1H']} | "
        f"CHASE={diag_counts['CHASE']} | "
        f"SPREAD={diag_counts['SPREAD']} | "
        f"ENTRY_RULES={diag_counts['ENTRY_RULES']}"
    )

    for source in ("CORE", "TREND"):
        st = source_stats[source]
        print(
            f"{source} diag | total={st['total']} | "
            f"entry_ready={st['entry_ready']} | "
            f"score_ready={st['score_ready']} | "
            f"fully_ready={st['fully_ready']}"
        )

    near_misses.sort(key=lambda x: x["score"], reverse=True)

    print("Top rejected candidates:")
    for x in near_misses[:8]:
        print(
            f"  {x['symbol']:12} {x['source']:5} "
            f"score={x['score']:.2f}/{x['required_score']:.2f} "
            f"reject={x['reject_reason']} "
            f"TF15={'Y' if x['tf15'] else 'N'} "
            f"TF1H={'Y' if x['tf1h'] else 'N'} "
            f"CHASE={'Y' if x['chase'] else 'N'} "
            f"SPREAD={'Y' if x['spread'] else 'N'}"
        )

    core_eligible = [
        a for a in analyses if a["source"] == "CORE"
        and a["symbol"] not in state["positions"]
        and not symbol_in_cooldown(state, a["symbol"])
        and a["core_entry_ok"] and a["score"] >= profile["min_score"]
    ]
    core_eligible.sort(key=lambda x: x["score"], reverse=True)

    trend_min_score = profile["min_score"] + CONFIG["trend_score_bonus_required"]
    trend_eligible = [
        a for a in analyses if a["source"] == "TREND"
        and a["symbol"] not in state["positions"]
        and not symbol_in_cooldown(state, a["symbol"])
        and a["trend_entry_ok"] and a["score"] >= trend_min_score
    ]
    trend_eligible.sort(key=lambda x: (x["score"], x["trend_24h_change"]), reverse=True)

    if core_eligible:
        print("\nTop CORE candidates:")
        for a in core_eligible[:8]:
            print(f"  {a['symbol']:12} score={a['score']:.2f} reason={a['reason']}")
    else:
        print("\nNo CORE candidate passed the current adaptive threshold.")

    if trend_eligible:
        print("\nTop TREND candidates:")
        for a in trend_eligible[:5]:
            print(f"  {a['symbol']:12} score={a['score']:.2f} 24h={a['trend_24h_change']:+.1f}% reason={a['reason']}")
    else:
        print("No TREND candidate passed the stricter trend rules.")

    equity_before = portfolio_value(state, prices)
    free_slots = max(0, profile["max_positions"] - len(state["positions"]))
    new_slots = min(free_slots, CONFIG["max_new_positions_per_run"])

    if regime != "RISK_OFF" and new_slots > 0:
        opened = 0
        base_spend = max(1.0, equity_before * profile["size_fraction"])
        trend_open = sum(1 for p in state["positions"].values() if p.get("source") == "TREND")

        if trend_eligible and trend_open < CONFIG["max_trend_positions"] and opened < new_slots:
            best = trend_eligible[0]
            weak_extra_ok = regime != "WEAK" or best["score"] >= max(7.10, trend_min_score + 0.25)
            if weak_extra_ok and buy(
                state, best, min(base_spend * 0.70, 5.0),
                f"TREND_POOL|24h={best['trend_24h_change']:+.1f}%|{best['reason']}"
            ):
                opened += 1

        for a in core_eligible:
            if opened >= new_slots:
                break
            if buy(state, a, base_spend, f"CORE|{regime}|{a['reason']}"):
                opened += 1
    elif regime == "RISK_OFF":
        print("New buys blocked only because market is in genuine RISK_OFF / hard pause.")
    else:
        print("No free risk slots for new positions this run.")

    equity = portfolio_value(state, prices)
    update_drawdown(state, equity)
    save_state(state)

    closed = state["wins"] + state["losses"]
    win_rate = state["wins"] / closed * 100.0 if closed else 0.0
    avg_win = state["sum_win_pnl"] / state["wins"] if state["wins"] else 0.0
    avg_loss = state["sum_loss_pnl"] / state["losses"] if state["losses"] else 0.0
    profit_factor = state["sum_win_pnl"] / abs(state["sum_loss_pnl"]) if state["sum_loss_pnl"] < 0 else 0.0
    expectancy = state["realized_pnl_usdt"] / closed if closed else 0.0
    open_names = ", ".join(f"{s}({p.get('source','CORE')})" for s, p in state["positions"].items()) or "none"

    print(
        f"\nCash ${state['cash_usdt']:.4f} | Equity ${equity:.4f} | "
        f"Realized P/L ${state['realized_pnl_usdt']:+.4f} | W/L {state['wins']}/{state['losses']} | "
        f"WinRate {win_rate:.1f}% | LossStreak {state.get('loss_streak', 0)}"
    )
    print(
        f"AvgWin ${avg_win:+.4f} | AvgLoss ${avg_loss:+.4f} | ProfitFactor {profit_factor:.2f} | "
        f"Expectancy ${expectancy:+.4f}/trade | MaxDD {state.get('max_drawdown_pct',0.0)*100:.2f}%"
    )
    print(f"Open {open_names}")
    print("Run complete. V5.2 state saved for next scheduled run.")


if __name__ == "__main__":
    main()
