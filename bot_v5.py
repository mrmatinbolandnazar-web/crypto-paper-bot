#!/usr/bin/env python3
# Binance Paper Trading Bot v5 — GitHub Actions one-shot — SIMULATION ONLY
# Conservative upgrade of v4: scans the 50 most-liquid eligible USDT spot pairs,
# uses closed 5m candles, stricter multi-horizon confirmation, market-regime gating,
# cooldowns, and candle-aware hard stops. No API key. No real orders.

import csv
import json
import os
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

BASE_URL = "https://data-api.binance.vision"

CONFIG = {
    # Universe
    "candidate_count": 50,
    "interval": "5m",
    "candle_limit": 180,

    # Paper account — kept equal to v4 for clean comparison
    "starting_usdt": 20.0,
    "trade_size_usdt": 4.0,
    "max_open_positions": 2,
    "max_new_positions_per_run": 1,
    "fee_rate": 0.001,

    # Risk / exits
    "take_profit_pct": 0.0120,       # +1.20% gross target
    "stop_loss_pct": 0.0045,         # -0.45% hard stop
    "trailing_trigger_pct": 0.0075,  # arm after +0.75%
    "trailing_distance_pct": 0.0035, # trail by 0.35%
    "breakeven_trigger_pct": 0.0065, # after +0.65%
    "breakeven_floor_pct": 0.0025,   # protect roughly +0.25% gross
    "min_hold_minutes_for_trend_exit": 15,
    "max_hold_minutes": 120,
    "stale_profit_ceiling_pct": 0.0020,

    # Entry filters — deliberately stricter than v4
    "ema_fast": 9,
    "ema_slow": 21,
    "rsi_period": 14,
    "rsi_min": 48.0,
    "rsi_max": 65.0,
    "momentum_5m_min": 0.0003,   # +0.03% over one CLOSED 5m candle
    "momentum_15m_min": 0.0015,  # +0.15% over 15m
    "momentum_30m_min": 0.0000,  # must not be negative over 30m
    "volume_ratio_min": 0.90,
    "min_score_to_buy": 5.60,

    # Market regime gate
    "breadth_min": 0.45,
    "risk_off_breadth": 0.30,
    "btc_15m_crash_pct": -0.0050, # block new entries if BTC <= -0.50% / 15m

    # Cooldowns
    "symbol_cooldown_win_minutes": 30,
    "symbol_cooldown_loss_minutes": 90,
    "loss_streak_to_pause": 2,
    "global_pause_minutes": 45,

    # API pacing
    "api_sleep_seconds": 0.05,
}

STATE_FILE = "paper_state_v5.json"
TRADES_FILE = "paper_trades_v5.csv"

# Exclude stablecoins/fiat-like bases and leveraged-token suffixes from the top-volume universe.
EXCLUDED_BASES = {
    "USDT", "USDC", "FDUSD", "TUSD", "USDP", "DAI", "EUR", "TRY", "BRL",
    "GBP", "AUD", "BIDR", "IDRT", "UAH", "PLN", "RON", "ARS", "AEUR"
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
        return datetime.fromisoformat(value)
    except Exception:
        return None


def http_get(path, params=None):
    params = params or {}
    url = BASE_URL + path
    if params:
        url += "?" + urlencode(params)
    req = Request(url, headers={"User-Agent": "paper-bot-v5/1.0"})
    with urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode("utf-8"))


def eligible_spot_symbol(info):
    if info.get("status") != "TRADING":
        return False
    if info.get("quoteAsset") != "USDT":
        return False
    if info.get("isSpotTradingAllowed") is False:
        return False
    base = info.get("baseAsset", "")
    symbol = info.get("symbol", "")
    if not base or base in EXCLUDED_BASES:
        return False
    if any(base.endswith(sfx) for sfx in LEVERAGED_SUFFIXES):
        return False
    if any(symbol.endswith(sfx + "USDT") for sfx in LEVERAGED_SUFFIXES):
        return False
    return True


def available_symbols():
    """Select the 50 most-liquid eligible USDT spot pairs by 24h quote volume."""
    try:
        info = http_get("/api/v3/exchangeInfo")
        allowed = {
            s["symbol"] for s in info.get("symbols", [])
            if eligible_spot_symbol(s)
        }
        tickers = http_get("/api/v3/ticker/24hr")
        ranked = []
        for t in tickers:
            symbol = t.get("symbol")
            if symbol not in allowed:
                continue
            try:
                qv = float(t.get("quoteVolume", 0.0))
            except (TypeError, ValueError):
                qv = 0.0
            ranked.append((qv, symbol))
        ranked.sort(reverse=True)
        chosen = [symbol for _, symbol in ranked[:CONFIG["candidate_count"]]]
        if len(chosen) >= 20:
            return chosen
    except Exception as e:
        print(f"Universe selection warning: {e}")

    # Conservative fallback list if exchange metadata/ticker endpoint is temporarily unavailable.
    fallback = [
        "BTCUSDT","ETHUSDT","BNBUSDT","SOLUSDT","XRPUSDT","DOGEUSDT","ADAUSDT","TRXUSDT","LINKUSDT","AVAXUSDT",
        "SUIUSDT","TONUSDT","NEARUSDT","DOTUSDT","LTCUSDT","BCHUSDT","APTUSDT","ARBUSDT","OPUSDT","PEPEUSDT",
        "UNIUSDT","ATOMUSDT","FILUSDT","ETCUSDT","SHIBUSDT","HBARUSDT","XLMUSDT","ICPUSDT","AAVEUSDT","INJUSDT",
        "RUNEUSDT","SEIUSDT","TIAUSDT","FETUSDT","RENDERUSDT","WIFUSDT","BONKUSDT","JUPUSDT","GALAUSDT","ALGOUSDT",
        "VETUSDT","MATICUSDT","MKRUSDT","LDOUSDT","CRVUSDT","DYDXUSDT","GRTUSDT","SANDUSDT","MANAUSDT","IMXUSDT"
    ]
    return fallback[:CONFIG["candidate_count"]]


def get_bars(symbol):
    data = http_get("/api/v3/klines", {
        "symbol": symbol,
        "interval": CONFIG["interval"],
        "limit": CONFIG["candle_limit"],
    })
    bars = [
        {
            "open_time": int(x[0]),
            "open": float(x[1]),
            "high": float(x[2]),
            "low": float(x[3]),
            "close": float(x[4]),
            "volume": float(x[5]),
            "close_time": int(x[6]),
        }
        for x in data
    ]
    # Binance normally returns the currently-forming candle as the last row.
    # V5 deliberately ignores it so volume and momentum are not distorted by partial candles.
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
    return 100.0 - (100.0 / (1.0 + rs))


def default_state():
    return {
        "cash_usdt": CONFIG["starting_usdt"],
        "positions": {},
        "realized_pnl_usdt": 0.0,
        "total_fees_usdt": 0.0,
        "wins": 0,
        "losses": 0,
        "loss_streak": 0,
        "cooldown_until": None,
        "symbol_cooldowns": {},
        "started_at": now_iso(),
    }


def normalize_state(state):
    defaults = default_state()
    for k, v in defaults.items():
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
                "time_utc", "symbol", "side", "price", "qty",
                "gross_usdt", "fee_usdt", "realized_pnl_usdt",
                "score", "reason"
            ])


def log_trade(symbol, side, price, qty, gross, fee, pnl, score, reason):
    ensure_trade_csv()
    with open(TRADES_FILE, "a", newline="", encoding="utf-8") as f:
        csv.writer(f).writerow([
            now_iso(), symbol, side, f"{price:.10f}", f"{qty:.10f}",
            f"{gross:.6f}", f"{fee:.6f}", f"{pnl:.6f}",
            f"{score:.3f}", reason,
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
        if (parse_iso(ts) and parse_iso(ts) > now)
    }
    until = parse_iso(state.get("cooldown_until"))
    if until and until <= now:
        state["cooldown_until"] = None


def buy(state, symbol, price, score, reason):
    if symbol in state["positions"]:
        return False
    if symbol_in_cooldown(state, symbol):
        return False
    if in_global_cooldown(state):
        return False
    if len(state["positions"]) >= CONFIG["max_open_positions"]:
        return False

    spend = min(CONFIG["trade_size_usdt"], state["cash_usdt"])
    if spend < 1.0:
        return False

    fee = spend * CONFIG["fee_rate"]
    usable = spend - fee
    qty = usable / price

    state["cash_usdt"] -= spend
    state["total_fees_usdt"] += fee
    state["positions"][symbol] = {
        "entry_price": price,
        "qty": qty,
        "cost_usdt": spend,
        "entry_fee_usdt": fee,
        "peak_price": price,
        "entry_score": score,
        "opened_at": now_iso(),
    }

    log_trade(symbol, "BUY", price, qty, spend, fee, 0.0, score, reason)
    print(f">>> BUY  {symbol} @ {price:.8f} | ${spend:.2f} paper | score={score:.2f} | {reason}")
    return True


def sell(state, symbol, price, reason):
    pos = state["positions"].get(symbol)
    if not pos:
        return None

    gross = pos["qty"] * price
    exit_fee = gross * CONFIG["fee_rate"]
    net = gross - exit_fee
    pnl = net - pos["cost_usdt"]

    state["cash_usdt"] += net
    state["realized_pnl_usdt"] += pnl
    state["total_fees_usdt"] += exit_fee

    if pnl >= 0:
        state["wins"] += 1
        state["loss_streak"] = 0
        cooldown_min = CONFIG["symbol_cooldown_win_minutes"]
    else:
        state["losses"] += 1
        state["loss_streak"] = int(state.get("loss_streak", 0)) + 1
        cooldown_min = CONFIG["symbol_cooldown_loss_minutes"]
        if state["loss_streak"] >= CONFIG["loss_streak_to_pause"]:
            state["cooldown_until"] = (
                now_dt() + timedelta(minutes=CONFIG["global_pause_minutes"])
            ).isoformat()
            print(f"!!! GLOBAL PAUSE armed for {CONFIG['global_pause_minutes']}m after loss streak={state['loss_streak']}")

    state.setdefault("symbol_cooldowns", {})[symbol] = (
        now_dt() + timedelta(minutes=cooldown_min)
    ).isoformat()

    log_trade(
        symbol, "SELL", price, pos["qty"], gross, exit_fee, pnl,
        pos.get("entry_score", 0.0), reason,
    )
    del state["positions"][symbol]
    print(f"<<< SELL {symbol} @ {price:.8f} | P/L ${pnl:+.4f} | {reason}")
    return pnl


def analyze(symbol):
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

    if None in (ef, es, ef_prev, es_prev, rr):
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

    score = 0.0
    reasons = []

    if price > ef > es:
        score += 1.40
        reasons.append("trend")
    if fast_slope > 0 and slow_slope >= -0.0002:
        score += 0.80
        reasons.append("slope")

    if 50.0 <= rr <= 62.0:
        score += 1.00
        reasons.append("rsi")
    elif CONFIG["rsi_min"] <= rr <= CONFIG["rsi_max"]:
        score += 0.60
        reasons.append("rsi_ok")

    if mom5 >= CONFIG["momentum_5m_min"]:
        score += 0.80
        reasons.append("mom5")
    if mom15 >= CONFIG["momentum_15m_min"]:
        score += 1.00
        reasons.append("mom15")
    if mom30 >= CONFIG["momentum_30m_min"]:
        score += 0.50
        reasons.append("mom30")

    if vol_ratio >= 1.10:
        score += min(1.10, 0.90 + (vol_ratio - 1.10) * 0.25)
        reasons.append("volume")
    elif vol_ratio >= CONFIG["volume_ratio_min"]:
        score += 0.50
        reasons.append("volume_ok")

    if 0.0005 <= trend_gap <= 0.008:
        score += 0.35
        reasons.append("gap")

    # Avoid chasing abrupt 5m spikes even if the rest of the score is high.
    if mom5 > 0.015 or rr > CONFIG["rsi_max"]:
        score -= 1.25
        reasons.append("hot_penalty")

    hard_entry_ok = (
        price > ef > es
        and fast_slope > 0
        and CONFIG["rsi_min"] <= rr <= CONFIG["rsi_max"]
        and mom5 >= CONFIG["momentum_5m_min"]
        and mom15 >= CONFIG["momentum_15m_min"]
        and mom30 >= CONFIG["momentum_30m_min"]
        and vol_ratio >= CONFIG["volume_ratio_min"]
    )

    return {
        "symbol": symbol,
        "price": price,
        "high": last["high"],
        "low": last["low"],
        "ema_fast": ef,
        "ema_slow": es,
        "fast_slope": fast_slope,
        "slow_slope": slow_slope,
        "rsi": rr,
        "mom5": mom5,
        "mom15": mom15,
        "mom30": mom30,
        "vol_ratio": vol_ratio,
        "score": score,
        "hard_entry_ok": hard_entry_ok,
        "reason": "+".join(reasons) if reasons else "weak",
    }


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
    close = a["price"]
    candle_high = a["high"]
    candle_low = a["low"]
    previous_peak = max(pos.get("peak_price", entry), entry)

    hard_stop = entry * (1.0 - CONFIG["stop_loss_pct"])
    take_profit = entry * (1.0 + CONFIG["take_profit_pct"])

    # Conservative same-candle assumption: if both hard stop and target could have hit,
    # count the stop first rather than choosing the optimistic path.
    if candle_low <= hard_stop:
        sell(state, symbol, hard_stop, "HARD_STOP")
        return

    if candle_high >= take_profit:
        sell(state, symbol, take_profit, "TAKE_PROFIT")
        return

    # Trailing/breakeven protection only uses a peak that was already known before this candle.
    previous_peak_change = previous_peak / entry - 1.0
    if previous_peak_change >= CONFIG["trailing_trigger_pct"]:
        trail_price = previous_peak * (1.0 - CONFIG["trailing_distance_pct"])
        if candle_low <= trail_price:
            sell(state, symbol, trail_price, "TRAILING_STOP")
            return

    if previous_peak_change >= CONFIG["breakeven_trigger_pct"]:
        floor_price = entry * (1.0 + CONFIG["breakeven_floor_pct"])
        if candle_low <= floor_price:
            sell(state, symbol, floor_price, "PROTECT_PROFIT")
            return

    pos["peak_price"] = max(previous_peak, candle_high, close)

    age = position_age_minutes(pos)
    change = close / entry - 1.0

    # Trend exit is less twitchy than v4: require age + EMA break + negative 15m momentum.
    if (
        age >= CONFIG["min_hold_minutes_for_trend_exit"]
        and a["ema_fast"] < a["ema_slow"]
        and a["mom15"] < 0
    ):
        sell(state, symbol, close, "CONFIRMED_TREND_LOST")
        return

    # Don't let a stale position occupy a slot for hours if it has made little progress.
    if (
        age >= CONFIG["max_hold_minutes"]
        and change < CONFIG["stale_profit_ceiling_pct"]
        and a["mom15"] <= 0
    ):
        sell(state, symbol, close, "TIME_EXIT")


def portfolio_value(state, price_map):
    total = state["cash_usdt"]
    for symbol, pos in state["positions"].items():
        p = price_map.get(symbol, pos["entry_price"])
        total += pos["qty"] * p
    return total


def market_regime(analyses):
    if not analyses:
        return False, 0.0, "no_data"

    trend_positive = sum(
        1 for a in analyses
        if a["ema_fast"] > a["ema_slow"] and a["mom15"] > 0
    )
    breadth = trend_positive / len(analyses)
    btc = next((a for a in analyses if a["symbol"] == "BTCUSDT"), None)

    if breadth < CONFIG["risk_off_breadth"]:
        return False, breadth, "breadth_risk_off"

    if btc and btc["mom15"] <= CONFIG["btc_15m_crash_pct"]:
        return False, breadth, "btc_fast_drop"

    if breadth < CONFIG["breadth_min"]:
        return False, breadth, "breadth_weak"

    # When BTC is available, avoid opening alt longs while its short trend is clearly bearish,
    # unless broad market participation is unusually strong.
    if btc and btc["ema_fast"] < btc["ema_slow"] and breadth < 0.65:
        return False, breadth, "btc_trend_down"

    return True, breadth, "market_ok"


def main():
    print("=" * 88)
    print("BINANCE PAPER TRADING BOT v5 — GITHUB ACTIONS — SIMULATION ONLY")
    print("50 liquid USDT spot pairs | closed candles | strict entries | risk gate | no real orders")
    print("=" * 88)

    state = load_state()
    cleanup_cooldowns(state)
    ensure_trade_csv()

    symbols = available_symbols()
    print(f"Active candidates: {len(symbols)}")
    print(", ".join(symbols))

    analyses = []
    prices = {}

    print(f"\n[{now_iso()}]")
    for symbol in symbols:
        try:
            a = analyze(symbol)
            analyses.append(a)
            prices[symbol] = a["price"]
            manage_open_position(state, a)
            print(
                f"{symbol:12} p={a['price']:.8f} "
                f"RSI={a['rsi']:5.1f} "
                f"M5={a['mom5']*100:+.2f}% "
                f"M15={a['mom15']*100:+.2f}% "
                f"VOLx={a['vol_ratio']:.2f} "
                f"SCORE={a['score']:.2f} "
                f"ENTRY={'Y' if a['hard_entry_ok'] else 'N'}"
            )
            time.sleep(CONFIG["api_sleep_seconds"])
        except (HTTPError, URLError, TimeoutError, ValueError) as e:
            print(f"{symbol:12} DATA ERROR: {e}")
        except Exception as e:
            print(f"{symbol:12} ERROR: {e}")

    market_ok, breadth, market_reason = market_regime(analyses)
    print(f"\nMarket gate: {'OPEN' if market_ok else 'BLOCKED'} | breadth={breadth*100:.1f}% | {market_reason}")

    if in_global_cooldown(state):
        print(f"Global cooldown active until {state.get('cooldown_until')}")
        market_ok = False

    eligible = [
        a for a in analyses
        if a["symbol"] not in state["positions"]
        and not symbol_in_cooldown(state, a["symbol"])
        and a["hard_entry_ok"]
        and a["score"] >= CONFIG["min_score_to_buy"]
    ]
    eligible.sort(key=lambda x: x["score"], reverse=True)

    if eligible:
        print("\nTop strict candidates:")
        for a in eligible[:10]:
            print(f"  {a['symbol']:12} score={a['score']:.2f} reason={a['reason']}")
    else:
        print("\nNo candidate passed all V5 entry filters.")

    free_slots = CONFIG["max_open_positions"] - len(state["positions"])
    new_slots = min(free_slots, CONFIG["max_new_positions_per_run"])

    if market_ok and new_slots > 0 and eligible:
        opened = 0
        for a in eligible:
            if opened >= new_slots:
                break
            if buy(state, a["symbol"], a["price"], a["score"], a["reason"]):
                opened += 1
    elif not market_ok:
        print("New buys skipped by V5 risk gate/cooldown.")

    save_state(state)

    equity = portfolio_value(state, prices)
    closed = state["wins"] + state["losses"]
    win_rate = (state["wins"] / closed * 100.0) if closed else 0.0
    open_names = ", ".join(state["positions"].keys()) or "none"

    print(
        f"\nCash ${state['cash_usdt']:.4f} | "
        f"Equity ${equity:.4f} | "
        f"Realized P/L ${state['realized_pnl_usdt']:+.4f} | "
        f"W/L {state['wins']}/{state['losses']} | "
        f"WinRate {win_rate:.1f}% | "
        f"LossStreak {state.get('loss_streak', 0)} | "
        f"Open {open_names}"
    )
    print("Run complete. V5 state saved for next scheduled run.")


if __name__ == "__main__":
    main()
