#!/usr/bin/env python3
# Binance Paper Trading Bot v3 — SIMULATION ONLY
# 25 candidate symbols, ranks signals, opens at most 2 paper positions.
# No API key. No real orders.

import csv
import json
import os
import time
from datetime import datetime, timezone
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

BASE_URL = "https://data-api.binance.vision"

CONFIG = {
    "candidate_symbols": [
        "BTCUSDT","ETHUSDT","BNBUSDT","SOLUSDT","XRPUSDT",
        "DOGEUSDT","ADAUSDT","TRXUSDT","LINKUSDT","AVAXUSDT",
        "SUIUSDT","TONUSDT","NEARUSDT","DOTUSDT","LTCUSDT",
        "BCHUSDT","APTUSDT","ARBUSDT","OPUSDT","PEPEUSDT",
        "UNIUSDT","ATOMUSDT","FILUSDT","ETCUSDT","SHIBUSDT"
    ],
    "interval": "1m",
    "candle_limit": 150,
    "starting_usdt": 20.0,
    "trade_size_usdt": 4.0,
    "max_open_positions": 2,

    # Paper assumptions
    "fee_rate": 0.001,
    "take_profit_pct": 0.012,      # +1.2%
    "stop_loss_pct": 0.006,        # -0.6%
    "trailing_trigger_pct": 0.008, # enable trailing after +0.8%
    "trailing_distance_pct": 0.004,# trail by 0.4%

    # Signal filters
    "ema_fast": 9,
    "ema_slow": 21,
    "rsi_period": 14,
    "rsi_min": 44.0,
    "rsi_max": 68.0,
    "momentum_5m_min": 0.0015,     # +0.15%
    "volume_ratio_min": 1.05,

    # Execution
    "min_score_to_buy": 3.2,
    "loop_seconds": 30
}

STATE_FILE = "paper_state_v3.json"
TRADES_FILE = "paper_trades_v3.csv"

def now_iso():
    return datetime.now(timezone.utc).isoformat()

def http_get(path, params=None):
    params = params or {}
    url = BASE_URL + path
    if params:
        url += "?" + urlencode(params)
    req = Request(url, headers={"User-Agent":"paper-bot-v3/1.0"})
    with urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode("utf-8"))

def available_symbols():
    """Return candidate symbols that currently exist and are trading."""
    try:
        info = http_get("/api/v3/exchangeInfo")
        active = {
            s["symbol"] for s in info.get("symbols", [])
            if s.get("status") == "TRADING"
        }
        chosen = [s for s in CONFIG["candidate_symbols"] if s in active]
        return chosen or CONFIG["candidate_symbols"][:10]
    except Exception:
        # If exchangeInfo is unavailable, still let the bot try the list.
        return CONFIG["candidate_symbols"]

def get_bars(symbol):
    data = http_get("/api/v3/klines", {
        "symbol": symbol,
        "interval": CONFIG["interval"],
        "limit": CONFIG["candle_limit"]
    })
    return [
        {
            "close": float(x[4]),
            "volume": float(x[5])
        }
        for x in data
    ]

def ema(values, period):
    if len(values) < period:
        return None
    out = sum(values[:period]) / period
    k = 2 / (period + 1)
    for v in values[period:]:
        out = v*k + out*(1-k)
    return out

def rsi(values, period):
    if len(values) < period + 1:
        return None
    gains, losses = [], []
    for i in range(-period, 0):
        d = values[i] - values[i-1]
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
        "started_at": now_iso()
    }

def load_state():
    if not os.path.exists(STATE_FILE):
        return default_state()
    with open(STATE_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

def ensure_trade_csv():
    if not os.path.exists(TRADES_FILE):
        with open(TRADES_FILE, "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow([
                "time_utc","symbol","side","price","qty",
                "gross_usdt","fee_usdt","realized_pnl_usdt",
                "score","reason"
            ])

def log_trade(symbol, side, price, qty, gross, fee, pnl, score, reason):
    ensure_trade_csv()
    with open(TRADES_FILE, "a", newline="", encoding="utf-8") as f:
        csv.writer(f).writerow([
            now_iso(), symbol, side, f"{price:.10f}", f"{qty:.10f}",
            f"{gross:.6f}", f"{fee:.6f}", f"{pnl:.6f}",
            f"{score:.3f}", reason
        ])

def buy(state, symbol, price, score, reason):
    if symbol in state["positions"]:
        return False
    if len(state["positions"]) >= CONFIG["max_open_positions"]:
        return False

    spend = min(CONFIG["trade_size_usdt"], state["cash_usdt"])
    if spend <= 0:
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
        "opened_at": now_iso()
    }

    log_trade(symbol, "BUY", price, qty, spend, fee, 0.0, score, reason)
    print(f">>> BUY  {symbol} @ {price:.8f} | ${spend:.2f} paper | score={score:.2f}")
    return True

def sell(state, symbol, price, reason):
    pos = state["positions"].get(symbol)
    if not pos:
        return

    gross = pos["qty"] * price
    exit_fee = gross * CONFIG["fee_rate"]
    net = gross - exit_fee
    pnl = net - pos["cost_usdt"]

    state["cash_usdt"] += net
    state["realized_pnl_usdt"] += pnl
    state["total_fees_usdt"] += exit_fee

    if pnl >= 0:
        state["wins"] += 1
    else:
        state["losses"] += 1

    log_trade(
        symbol, "SELL", price, pos["qty"], gross, exit_fee, pnl,
        pos.get("entry_score", 0.0), reason
    )
    del state["positions"][symbol]
    print(f"<<< SELL {symbol} @ {price:.8f} | P/L ${pnl:+.4f} | {reason}")

def analyze(symbol):
    bars = get_bars(symbol)
    closes = [b["close"] for b in bars]
    vols = [b["volume"] for b in bars]

    price = closes[-1]
    ef = ema(closes, CONFIG["ema_fast"])
    es = ema(closes, CONFIG["ema_slow"])
    rr = rsi(closes, CONFIG["rsi_period"])

    if None in (ef, es, rr):
        raise ValueError("not enough data")

    mom5 = (price / closes[-6] - 1.0) if len(closes) >= 6 else 0.0
    prev_vols = vols[-21:-1]
    avg_vol = sum(prev_vols) / len(prev_vols) if prev_vols else 0.0
    vol_ratio = vols[-1] / avg_vol if avg_vol > 0 else 0.0

    # Score ranges roughly 0..5
    score = 0.0
    reasons = []

    trend_gap = (ef / es - 1.0) if es else 0.0
    if ef > es:
        score += 1.25
        reasons.append("trend")

    if CONFIG["rsi_min"] <= rr <= CONFIG["rsi_max"]:
        score += 1.00
        reasons.append("rsi")
    elif rr < CONFIG["rsi_min"] and rr >= 35:
        score += 0.35

    if mom5 >= CONFIG["momentum_5m_min"]:
        score += 1.15
        reasons.append("momentum")
    elif mom5 > 0:
        score += 0.35

    if vol_ratio >= CONFIG["volume_ratio_min"]:
        score += min(1.10, 0.75 + (vol_ratio - CONFIG["volume_ratio_min"]) * 0.5)
        reasons.append("volume")

    # Small bonus for a healthy positive EMA gap
    if 0 < trend_gap < 0.01:
        score += min(0.5, trend_gap * 100)

    return {
        "symbol": symbol,
        "price": price,
        "ema_fast": ef,
        "ema_slow": es,
        "rsi": rr,
        "mom5": mom5,
        "vol_ratio": vol_ratio,
        "score": score,
        "reason": "+".join(reasons) if reasons else "weak"
    }

def manage_open_position(state, a):
    symbol = a["symbol"]
    pos = state["positions"].get(symbol)
    if not pos:
        return

    price = a["price"]
    pos["peak_price"] = max(pos.get("peak_price", price), price)

    change = price / pos["entry_price"] - 1.0
    peak_change = pos["peak_price"] / pos["entry_price"] - 1.0
    draw_from_peak = price / pos["peak_price"] - 1.0

    if change >= CONFIG["take_profit_pct"]:
        sell(state, symbol, price, "TAKE_PROFIT")
    elif change <= -CONFIG["stop_loss_pct"]:
        sell(state, symbol, price, "STOP_LOSS")
    elif (
        peak_change >= CONFIG["trailing_trigger_pct"]
        and draw_from_peak <= -CONFIG["trailing_distance_pct"]
    ):
        sell(state, symbol, price, "TRAILING_STOP")
    elif a["ema_fast"] < a["ema_slow"] and a["mom5"] < 0:
        sell(state, symbol, price, "TREND_LOST")

def portfolio_value(state, price_map):
    total = state["cash_usdt"]
    for symbol, pos in state["positions"].items():
        p = price_map.get(symbol, pos["entry_price"])
        total += pos["qty"] * p
    return total

def main():
    print("=" * 72)
    print("BINANCE PAPER TRADING BOT v3 — SIMULATION ONLY")
    print("Ranks up to 25 candidates and opens only the 2 best paper signals.")
    print("No API key. No real orders.")
    print("=" * 72)

    state = load_state()
    ensure_trade_csv()

    symbols = available_symbols()
    print(f"Active candidates: {len(symbols)}")
    print(", ".join(symbols))

    while True:
        analyses = []
        prices = {}

        try:
            print(f"\n[{now_iso()}]")

            for symbol in symbols:
                try:
                    a = analyze(symbol)
                    analyses.append(a)
                    prices[symbol] = a["price"]
                    manage_open_position(state, a)
                    print(
                        f"{symbol:10} p={a['price']:.8f} "
                        f"RSI={a['rsi']:5.1f} "
                        f"MOM5={a['mom5']*100:+.2f}% "
                        f"VOLx={a['vol_ratio']:.2f} "
                        f"SCORE={a['score']:.2f}"
                    )
                    time.sleep(0.10)
                except (HTTPError, URLError, TimeoutError, ValueError) as e:
                    print(f"{symbol:10} DATA ERROR: {e}")
                except Exception as e:
                    print(f"{symbol:10} ERROR: {e}")

            # Rank eligible symbols and open only best available slots.
            eligible = [
                a for a in analyses
                if a["symbol"] not in state["positions"]
                and a["ema_fast"] > a["ema_slow"]
                and a["rsi"] <= CONFIG["rsi_max"]
                and a["score"] >= CONFIG["min_score_to_buy"]
            ]
            eligible.sort(key=lambda x: x["score"], reverse=True)

            free_slots = CONFIG["max_open_positions"] - len(state["positions"])
            if free_slots > 0 and eligible:
                print("\nTop candidates:")
                for a in eligible[:5]:
                    print(f"  {a['symbol']} score={a['score']:.2f} reason={a['reason']}")

                for a in eligible[:free_slots]:
                    buy(
                        state, a["symbol"], a["price"],
                        a["score"], a["reason"]
                    )

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
                f"WinRate {win_rate:.1f}% | Open {open_names}"
            )
            print(f"Sleeping {CONFIG['loop_seconds']}s...")
            time.sleep(CONFIG["loop_seconds"])

        except KeyboardInterrupt:
            save_state(state)
            print("\nStopped. State saved.")
            break

if __name__ == "__main__":
    main()
