#!/usr/bin/env python3
# V5.2 30-day historical replay - SIMULATION ONLY.
# Reuses the current bot's exact analyze/regime/risk/buy/sell/manage logic.
# It never loads/saves the live paper state and never writes the live trade CSV.
#
# Limitation: historical order-book spread snapshots are unavailable here,
# so spread is forced to PASS during replay.

import bisect
import csv
import json
import math
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import bot_v5_2_balanced as b
from cyrus_trader_v7.engine import CyrusTraderV7

DAYS = 90
WARMUP_DAYS = 4
UNIVERSE_TARGET = 82
FIVE_MS = 5 * 60 * 1000

CACHE = Path(".backtest_cache_v5_2_oos_pre_20260228")
REPORT = Path("backtest_cyrus_v7_oos2_90d_report.txt")
TRADES = Path("backtest_cyrus_v7_oos2_90d_trades.csv")
CACHE.mkdir(exist_ok=True)

SERIES = {}
TIMES = {}
CUR_MS = 0
CUR_DT = None
BT_TRADES = []


def iso_ms(ms):
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat()


def floor5(dt):
    ms = int(dt.timestamp() * 1000)
    return ms - (ms % FIVE_MS)


def fetch_5m(symbol, start_ms, end_ms):
    sp = datetime.fromtimestamp(start_ms/1000, tz=timezone.utc).strftime("%Y%m%d")
    ep = datetime.fromtimestamp(end_ms/1000, tz=timezone.utc).strftime("%Y%m%d")
    path = CACHE / f"{symbol}_5m_{sp}_{ep}.json"
    if path.exists():
        try:
            data = json.loads(path.read_text())
            if data:
                return data
        except Exception:
            pass

    out = []
    cursor = start_ms
    while cursor < end_ms:
        rows = b.http_get("/api/v3/klines", {
            "symbol": symbol,
            "interval": "5m",
            "startTime": cursor,
            "endTime": end_ms,
            "limit": 1000,
        })
        if not rows:
            break

        for x in rows:
            ct = int(x[6])
            if start_ms <= ct <= end_ms:
                out.append({
                    "open_time": int(x[0]),
                    "open": float(x[1]),
                    "high": float(x[2]),
                    "low": float(x[3]),
                    "close": float(x[4]),
                    "volume": float(x[5]),
                    "close_time": ct,
                    "quote_volume": float(x[7]),
                })

        last = int(rows[-1][6])
        nxt = max(cursor + FIVE_MS, last + 1)
        if nxt <= cursor:
            break
        cursor = nxt
        time.sleep(max(0.02, float(b.CONFIG.get("api_sleep_seconds", 0.03))))
        if len(rows) < 1000:
            break

    dedup = {x["close_time"]: x for x in out}
    out = [dedup[k] for k in sorted(dedup)]
    path.write_text(json.dumps(out, separators=(",", ":")))
    return out


def resample(rows, factor):
    bucket_ms = FIVE_MS * factor
    buckets = {}
    for r in rows:
        key = r["open_time"] - (r["open_time"] % bucket_ms)
        buckets.setdefault(key, []).append(r)

    out = []
    for key in sorted(buckets):
        xs = sorted(buckets[key], key=lambda z: z["open_time"])
        if len(xs) != factor:
            continue
        if any(xs[i]["open_time"] - xs[i-1]["open_time"] != FIVE_MS for i in range(1, len(xs))):
            continue
        out.append({
            "open_time": xs[0]["open_time"],
            "open": xs[0]["open"],
            "high": max(x["high"] for x in xs),
            "low": min(x["low"] for x in xs),
            "close": xs[-1]["close"],
            "volume": sum(x["volume"] for x in xs),
            "close_time": xs[-1]["close_time"],
            "quote_volume": sum(x["quote_volume"] for x in xs),
        })
    return out


def hist_get_bars(symbol, interval=None, limit=None):
    interval = interval or b.CONFIG["interval"]
    limit = limit or b.CONFIG["candle_limit"]
    rows = SERIES[symbol][interval]
    ts = TIMES[symbol][interval]
    i = bisect.bisect_right(ts, CUR_MS)
    return rows[max(0, i-limit):i]


def hist_spread(symbol):
    return 0.0


def hist_now_dt():
    return CUR_DT


def hist_now_iso():
    return CUR_DT.isoformat()


def fake_log_trade(symbol, side, source, price, qty, gross, fee, pnl, score,
                   stop_pct, take_profit_pct, reason):
    BT_TRADES.append({
        "time_utc": CUR_DT.isoformat(),
        "symbol": symbol,
        "side": side,
        "source": source,
        "price": price,
        "qty": qty,
        "gross_usdt": gross,
        "fee_usdt": fee,
        "realized_pnl_usdt": pnl,
        "score": score,
        "stop_pct": stop_pct,
        "take_profit_pct": take_profit_pct,
        "reason": reason,
    })


def rolling24(symbol):
    rows = SERIES[symbol]["5m"]
    ts = TIMES[symbol]["5m"]
    i = bisect.bisect_right(ts, CUR_MS)
    if i < 289:
        return None
    cur = rows[i-1]["close"]
    old = rows[i-289]["close"]
    if old <= 0:
        return None
    recent = rows[i-288:i]
    return {
        "change_pct": (cur / old - 1.0) * 100.0,
        "quote_volume": sum(x["quote_volume"] for x in recent),
    }


def trend_watch(universe):
    ranked = []
    meta = {}
    for symbol in universe:
        x = rolling24(symbol)
        if not x:
            continue
        qv = x["quote_volume"]
        chg = x["change_pct"]
        meta[symbol] = x
        if qv < b.CONFIG["trend_quote_volume_min"]:
            continue
        if not (b.CONFIG["trend_24h_change_min"] <= chg <= b.CONFIG["trend_24h_change_max"]):
            continue
        rank = chg + 0.45 * math.log10(max(qv, 1.0))
        ranked.append((rank, qv, chg, symbol))

    ranked.sort(reverse=True)
    top = ranked[:b.CONFIG["trend_prefilter_count"]]
    return {x[3] for x in top[:b.CONFIG["trend_scan_count"]]}, meta


def clean_state():
    s = b.default_state()
    s["cash_usdt"] = float(b.CONFIG["starting_usdt"])
    s["positions"] = {}
    s["realized_pnl_usdt"] = 0.0
    s["total_fees_usdt"] = 0.0
    s["wins"] = 0
    s["losses"] = 0
    s["loss_streak"] = 0
    s["cooldown_until"] = None
    s["symbol_cooldowns"] = {}
    s["sum_win_pnl"] = 0.0
    s["sum_loss_pnl"] = 0.0
    s["peak_equity"] = float(b.CONFIG["starting_usdt"])
    s["max_drawdown_pct"] = 0.0
    s["recovery_confirm_runs"] = 0
    s["last_regime"] = None
    return s


def main():
    global CUR_MS, CUR_DT

    end_ms = floor5(datetime(2026, 2, 28, 14, 5, tzinfo=timezone.utc))
    start_ms = end_ms - DAYS * 24 * 60 * 60 * 1000
    data_start = start_ms - WARMUP_DAYS * 24 * 60 * 60 * 1000

    print("=" * 88)
    print("V5.2 90-DAY HISTORICAL REPLAY - SIMULATION ONLY")
    print("Exact current analyze/regime/risk/buy/sell/manage logic is reused.")
    print("Live paper state and live paper trades are NOT touched.")
    print("Historical spread unavailable -> spread forced PASS.")
    print("=" * 88)
    print(f"Period: {iso_ms(start_ms)} -> {iso_ms(end_ms)}")

    info_map, ticker_map = b.get_market_catalog()
    core_symbols, _, _ = b.build_core_universe(info_map, ticker_map)
    core_set = set(core_symbols)
    current_trend, _ = b.build_trend_watch(core_set, ticker_map)

    liquid = sorted(
        ticker_map,
        key=lambda s: float(ticker_map[s].get("quote_volume", 0.0) or 0.0),
        reverse=True
    )
    universe = []
    for s in list(core_symbols) + list(current_trend) + liquid:
        if s in info_map and s not in universe:
            universe.append(s)
        if len(universe) >= UNIVERSE_TARGET:
            break

    print(f"Current CORE pool: {len(core_symbols)}")
    cached_90d = sorted(
        x.name.split("_5m_")[0]
        for x in CACHE.glob("*_5m_20260525_20260827.json")
    )
    # FROZEN COMPARISON SNAPSHOT
    snapshot = __import__("json").loads(
        Path("frozen_universe_core_90d.json").read_text(encoding="utf-8")
    )

    frozen_universe = list(snapshot["universe"])
    frozen_core = set(snapshot["core_set"])

    if len(frozen_universe) != 82:
        raise RuntimeError(
            f"Frozen universe must contain 82 symbols, got {len(frozen_universe)}"
        )
    universe = frozen_universe
    core_set = frozen_core.intersection(universe)

    print(
        f"FROZEN comparison universe={len(universe)} "
        f"CORE={len(core_set)}"
    )

    print(f"Replay universe approximation: {len(universe)} symbols")
    print("Downloading/loading history. First run may take several minutes...")

    usable = []
    for n, symbol in enumerate(universe, 1):
        try:
            r5 = fetch_5m(symbol, data_start, end_ms)
            if len(r5) < 1500:
                print(f"[{n:02d}/{len(universe)}] {symbol}: insufficient history -> skip")
                continue
            r15 = resample(r5, 3)
            r1h = resample(r5, 12)
            if len(r15) < 200 or len(r1h) < 80:
                print(f"[{n:02d}/{len(universe)}] {symbol}: MTF insufficient -> skip")
                continue
            SERIES[symbol] = {"5m": r5, "15m": r15, "1h": r1h}
            TIMES[symbol] = {
                "5m": [x["close_time"] for x in r5],
                "15m": [x["close_time"] for x in r15],
                "1h": [x["close_time"] for x in r1h],
            }
            usable.append(symbol)
            print(f"[{n:02d}/{len(universe)}] {symbol}: OK")
        except Exception as e:
            print(f"[{n:02d}/{len(universe)}] {symbol}: ERROR {e}")

    if "BTCUSDT" not in usable or "ETHUSDT" not in usable:
        raise SystemExit("BTCUSDT and ETHUSDT history are required.")

    universe = usable
    core_set = core_set.intersection(universe)

    # Monkeypatch only in this backtest process.
    b.get_bars = hist_get_bars
    b.get_spread_pct = hist_spread
    b.now_dt = hist_now_dt
    b.now_iso = hist_now_iso
    b.log_trade = fake_log_trade

    replay_times = [
        t for t in TIMES["BTCUSDT"]["5m"]
        if start_ms <= t <= end_ms
    ]
    CUR_MS = replay_times[0]
    CUR_DT = datetime.fromtimestamp(CUR_MS / 1000, tz=timezone.utc)
    bot = CyrusTraderV7(mode="backtest")

    state = {
        "cash_usdt": 100.0,
        "positions": {},
        "loss_streak": 0,
        "drawdown": 0.0,
        "daily_pnl_usdt": 0.0,
        "daily_pnl_pct": 0.0,
    }

    start_equity = 100.0
    peak_equity = start_equity
    max_drawdown = 0.0
    closed_trades = []
    total_fees = 0.0
    market_counts = {}
    stage_counts = {}
    current_day = None

    print(f"Replay steps: {len(replay_times)}")
    print("Running CYRUS V6 replay...")

    for step, t_ms in enumerate(replay_times, 1):
        CUR_MS = t_ms
        CUR_DT = datetime.fromtimestamp(
            t_ms / 1000, tz=timezone.utc
        )
        now_iso = CUR_DT.isoformat()

        day_key = CUR_DT.date().isoformat()
        if day_key != current_day:
            current_day = day_key
            state["daily_pnl_usdt"] = 0.0
            state["daily_pnl_pct"] = 0.0

        # ---- Manage existing position first ----
        for symbol in list(state["positions"]):
            pos = state["positions"][symbol]

            try:
                entry_dt = datetime.fromisoformat(
                    pos["entry_time"]
                )
                if entry_dt.tzinfo is None:
                    entry_dt = entry_dt.replace(
                        tzinfo=timezone.utc
                    )

                age_minutes = (
                    CUR_DT - entry_dt
                ).total_seconds() / 60.0

                decision = bot.evaluate_position(
                    pos,
                    age_minutes,
                )
            except Exception as e:
                print(f"POSITION_ERROR {symbol} {now_iso}: {e}")
                continue

            if not decision:
                continue

            if decision.get("action") == "EXIT":
                equity_before = state["cash_usdt"]

                try:
                    bars = b.get_bars(symbol)
                    mark_price = float(bars[-1]["close"])
                    equity_before += (
                        float(pos["qty"]) * mark_price
                    )
                except Exception:
                    pass

                trade = bot.close_position(
                    pos,
                    float(decision["price"]),
                    decision["reason"],
                    now_iso,
                )

                pnl = float(trade["realized_pnl_usdt"])
                state["cash_usdt"] += (
                    float(trade["gross_spend_usdt"]) + pnl
                )

                total_fees += (
                    float(trade["entry_fee_usdt"])
                    + float(trade["exit_fee_usdt"])
                )

                # V6 diagnostic fields
                _entry = float(pos.get("entry_price", 0) or 0)
                _stop = float(pos.get("invalidation_price", 0) or 0)
                _highest = float(pos.get("highest_price", _entry) or _entry)
                _risk_abs = max(0.0, _entry - _stop)
                trade["initial_stop"] = _stop
                trade["initial_risk_pct"] = (
                    (_risk_abs / _entry) if _entry > 0 else 0.0
                )
                trade["highest_price"] = _highest
                trade["mfe_pct"] = (
                    ((_highest / _entry) - 1.0) if _entry > 0 else 0.0
                )
                trade["mfe_r"] = (
                    ((_highest - _entry) / _risk_abs)
                    if _risk_abs > 0 else 0.0
                )
                trade["breakeven_armed"] = bool(pos.get("breakeven_armed", False))
                trade["trailing_armed"] = bool(pos.get("trailing_armed", False))
                closed_trades.append(trade)
                del state["positions"][symbol]

                bot.protector.update_after_trade(
                    state,
                    pnl,
                    equity_before,
                    now_iso,
                )

        # ---- Equity / drawdown before any new entry ----
        equity = state["cash_usdt"]

        for symbol, pos in state["positions"].items():
            try:
                bars = b.get_bars(symbol)
                px = float(bars[-1]["close"])
                equity += float(pos["qty"]) * px
            except Exception:
                equity += float(pos["gross_spend_usdt"])

        peak_equity = max(peak_equity, equity)

        if peak_equity > 0:
            state["drawdown"] = (
                peak_equity - equity
            ) / peak_equity
            max_drawdown = max(
                max_drawdown,
                state["drawdown"],
            )

        # ---- V7 entry scan: max one open position ----
        if not state["positions"]:
            candidates = []

            for symbol in sorted(core_set):
                if symbol not in SERIES:
                    continue

                try:
                    result = bot.evaluate_entry(
                        symbol=symbol,
                        equity=equity,
                        portfolio_state=state,
                        time_utc=now_iso,
                    )
                except Exception as e:
                    print(f"ENTRY_ERROR {symbol} {now_iso}: {e}")
                    continue

                stage = result.get("stage", "UNKNOWN")
                stage_counts[stage] = (
                    stage_counts.get(stage, 0) + 1
                )

                market = result.get("market")
                if market is not None:
                    market_counts[market.regime] = (
                        market_counts.get(
                            market.regime, 0
                        ) + 1
                    )

                if result.get("action") == "OPEN":
                    sig = result["signal"]
                    candidates.append((
                        float(
                            sig.metadata.get(
                                "extension_pct", 999
                            )
                        ),
                        float(
                            sig.metadata.get(
                                "risk_pct", 999
                            )
                        ),
                        symbol,
                        result,
                    ))

            if candidates:
                candidates.sort(
                    key=lambda x: (x[0], x[1], x[2])
                )
                _, _, symbol, result = candidates[0]

                pos = result["position"]
                spend = float(pos["gross_spend_usdt"])

                if spend <= state["cash_usdt"]:
                    state["cash_usdt"] -= spend
                    state["positions"][symbol] = pos

        if step % 288 == 0 or step == len(replay_times):
            print(
                f"Progress {step/288.0:5.1f}d | "
                f"equity=${equity:.4f} | "
                f"closed={len(closed_trades):4d} | "
                f"DD={state['drawdown']*100:.2f}%"
            )

    # ---- Close final open position at final market price ----
    for symbol in list(state["positions"]):
        pos = state["positions"][symbol]

        try:
            bars = b.get_bars(symbol)
            px = float(bars[-1]["close"])
        except Exception:
            px = float(pos["entry_price"])

        trade = bot.close_position(
            pos,
            px,
            "V6_END_OF_TEST",
            CUR_DT.isoformat(),
        )

        pnl = float(trade["realized_pnl_usdt"])

        state["cash_usdt"] += (
            float(trade["gross_spend_usdt"]) + pnl
        )

        total_fees += (
            float(trade["entry_fee_usdt"])
            + float(trade["exit_fee_usdt"])
        )

        closed_trades.append(trade)
        del state["positions"][symbol]

    final_equity = state["cash_usdt"]
    net = final_equity - start_equity

    wins = [
        x for x in closed_trades
        if float(x["realized_pnl_usdt"]) > 0
    ]
    losses = [
        x for x in closed_trades
        if float(x["realized_pnl_usdt"]) <= 0
    ]

    gross_profit = sum(
        float(x["realized_pnl_usdt"])
        for x in wins
    )
    gross_loss = abs(sum(
        float(x["realized_pnl_usdt"])
        for x in losses
    ))

    pf = (
        gross_profit / gross_loss
        if gross_loss > 0 else float("inf")
    )

    n = len(closed_trades)
    wr = len(wins) / n * 100 if n else 0.0
    expectancy = net / n if n else 0.0

    lines = [
        "=" * 72,
        "CYRUS TRADER V7 - OOS2 90-DAY BACKTEST",
        "SIMULATION ONLY",
        "=" * 72,
        f"Period: {iso_ms(start_ms)} -> {iso_ms(end_ms)}",
        f"Universe: {len(universe)}",
        f"Frozen CORE: {len(core_set)}",
        f"Starting equity: ${start_equity:.4f}",
        f"Final equity:    ${final_equity:.4f}",
        f"Net P/L:         ${net:+.4f} ({net/start_equity*100:+.2f}%)",
        f"Closed trades:   {n}",
        f"W / L:           {len(wins)} / {len(losses)}",
        f"Win rate:        {wr:.1f}%",
        f"Profit factor:   {pf:.2f}",
        f"Expectancy:      ${expectancy:+.4f}/trade",
        f"Max drawdown:    {max_drawdown*100:.2f}%",
        f"Total fees:      ${total_fees:.4f}",
        "",
        f"Market counts: {market_counts}",
        f"Pipeline stages: {stage_counts}",
        "=" * 72,
    ]

    REPORT.write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )

    import csv

    fields = [
        "symbol", "setup", "entry_time", "exit_time",
        "entry_price", "exit_price", "qty",
        "gross_spend_usdt", "entry_fee_usdt",
        "exit_fee_usdt", "realized_pnl_usdt",
        "reason",
            "initial_stop",
            "initial_risk_pct",
            "highest_price",
            "mfe_pct",
            "mfe_r",
            "breakeven_armed",
            "trailing_armed",
            "extension_pct",
            "candle_move",
            "atr_pct",
            "risk_pct",
            "tf15_mom3",
            "tf15_fast_slope",
            "tf1h_mom3",
            "tf1h_fast_slope",
    ]

    with TRADES.open(
        "w", newline="", encoding="utf-8"
    ) as f:
        w = csv.DictWriter(
            f,
            fieldnames=fields,
            extrasaction="ignore",
        )
        w.writeheader()
        w.writerows(closed_trades)

    print()
    print("\n".join(lines))
    print(f"Report: {REPORT}")
    print(f"Trades: {TRADES}")


if __name__ == "__main__":
    main()
