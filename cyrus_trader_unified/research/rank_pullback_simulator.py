import json, math
from pathlib import Path
from types import SimpleNamespace
from collections import defaultdict
from cyrus_trader_unified.market_ranker import MarketRanker

CACHE = Path("/opt/crypto-paper-bot/.backtest_cache_v5_2")
START_MS = 1784901900000
END_MS   = 1787839500000
COST = 0.0026
STEP = 12
TOPN = 3

PROFILES = {
    "FAST":     {"tp":0.008, "sl":0.004, "max_bars":48},   # 4h
    "BALANCED": {"tp":0.015, "sl":0.006, "max_bars":96},   # 8h
    "RUNNER":   {"tp":0.025, "sl":0.008, "max_bars":96},   # 8h
}

def load(symbol):
    for name in (
        f"{symbol}_5m_20260724_20260827.json",
        f"{symbol}_5m_20260525_20260827.json",
    ):
        p=CACHE/name
        if not p.exists():
            continue
        try:
            raw=json.loads(p.read_text())
            out=[]
            for x in raw:
                if isinstance(x,dict):
                    t=int(x.get("close_time",x.get("closeTime",x.get("time",x.get("timestamp",0)))))
                    o,h,l,c,v=map(float,(x["open"],x["high"],x["low"],x["close"],x["volume"]))
                else:
                    if len(x)<7: continue
                    t=int(x[6]); o,h,l,c,v=map(float,(x[1],x[2],x[3],x[4],x[5]))
                if START_MS-4*86400000 <= t <= END_MS:
                    out.append({"t":t,"o":o,"h":h,"l":l,"c":c,"v":v})
            if len(out)>500:
                return out
        except Exception:
            pass
    return []

def ema(vals,n):
    if len(vals)<n: return None
    a=2/(n+1)
    e=sum(vals[:n])/n
    for x in vals[n:]:
        e=x*a+e*(1-a)
    return e

def ctx(symbol,bars,i,btc_safe,eth_safe):
    if i<180: return None
    c=[x["c"] for x in bars]
    e15f=ema(c[i-119:i+1],36)
    e15s=ema(c[i-179:i+1],72)
    e15f_prev=ema(c[i-122:i-2],36)
    mom15=c[i]/c[i-9]-1
    mom1h=c[i]/c[i-36]-1
    slope15=e15f/e15f_prev-1 if e15f_prev else 0
    e1f=ema(c[i-179:i+1:12],8)
    e1s=ema(c[i-179:i+1:12],15)
    e1f_prev=ema(c[i-191:i-11:12],8)
    slope1h=e1f/e1f_prev-1 if e1f and e1f_prev else 0
    trend15=bool(e15f and e15s and c[i]>e15f>e15s and slope15>0)
    trend1h=bool(e1f and e1s and c[i]>e1f>e1s and slope1h>0)
    rets=[c[j]/c[j-1]-1 for j in range(i-35,i+1)]
    vol=(sum(x*x for x in rets)/len(rets))**0.5*math.sqrt(12)
    regime="TREND_UP" if trend15 and trend1h else "RANGE"

    return SimpleNamespace(
        symbol=symbol, regime=regime,
        trend_5m=True, trend_15m=trend15, trend_1h=trend1h,
        volatility=vol, btc_safe=btc_safe, eth_safe=eth_safe,
        tf15_mom3=mom15, tf15_fast_slope=slope15,
        tf1h_mom3=mom1h, tf1h_fast_slope=slope1h
    )

def pf(vals):
    pos=sum(x for x in vals if x>0)
    neg=abs(sum(x for x in vals if x<0))
    return pos/neg if neg else float("inf")

def atr_pct(bars,i,n=14):
    if i < n:
        return 0.0
    trs=[]
    for j in range(i-n+1,i+1):
        prev=bars[j-1]["c"]
        tr=max(
            bars[j]["h"]-bars[j]["l"],
            abs(bars[j]["h"]-prev),
            abs(bars[j]["l"]-prev)
        )
        trs.append(tr)
    return (sum(trs)/len(trs))/bars[i]["c"]

def find_pullback_entry(bars,i,wait_bars=24):
    entry_ref=bars[i]["c"]

    closes=[x["c"] for x in bars]
    for j in range(i+1, min(i+wait_bars+1, len(bars)-1)):
        if j < 40:
            continue

        e20=ema(closes[j-39:j+1],20)
        if not e20:
            continue

        c=bars[j]
        p=bars[j-1]

        pullback = c["l"] <= e20*1.0025
        reclaim = c["c"] > e20 and c["c"] > c["o"] and c["c"] > p["c"]
        not_chasing = c["c"] <= entry_ref*1.010

        if pullback and reclaim and not_chasing:
            return j

    return None

def simulate_trade(bars,entry_i,max_bars=96):
    entry=bars[entry_i]["c"]
    atr=atr_pct(bars,entry_i)

    recent_low=min(x["l"] for x in bars[max(0,entry_i-12):entry_i+1])
    atr_stop=entry*(1-max(0.005, min(0.015, atr*1.8)))
    stop=max(recent_low*0.998, atr_stop)

    risk=(entry-stop)/entry
    if risk <= 0 or risk > 0.02:
        return None

    tp=entry*(1+max(0.015, risk*2.2))
    trail_arm=entry*(1+max(0.012, risk*1.5))
    highest=entry
    trail=None

    for j in range(entry_i+1, min(entry_i+max_bars+1, len(bars))):
        hi=bars[j]["h"]
        lo=bars[j]["l"]
        highest=max(highest,hi)

        if highest >= trail_arm:
            trail=max(stop, highest*(1-max(0.006, min(0.012, atr*1.5))))

        active_stop=max(stop, trail) if trail else stop

        if lo <= active_stop:
            gross=active_stop/entry-1
            reason="TRAIL" if trail and active_stop>stop else "SL"
            return gross-COST, j-entry_i, reason

        if hi >= tp:
            return tp/entry-1-COST, j-entry_i, "TP"

    j=min(entry_i+max_bars, len(bars)-1)
    return bars[j]["c"]/entry-1-COST, j-entry_i, "TIME"

files=list(CACHE.glob("*_5m_20260525_20260827.json"))
symbols=sorted({p.name.split("_5m_")[0] for p in files})
data={s:load(s) for s in symbols}
data={s:b for s,b in data.items() if b}

btc=data["BTCUSDT"]
eth=data.get("ETHUSDT")
maps={s:{x["t"]:j for j,x in enumerate(b)} for s,b in data.items()}
btc_map=maps["BTCUSDT"]
times=[x["t"] for x in btc if START_MS<=x["t"]<=END_MS]

ranker=MarketRanker()
results=[]
reasons=defaultdict(int)
holds=[]
events=0
signals=0
entered=0
active_until={}

for k,t in enumerate(times):
    if k%STEP: continue
    bi=btc_map.get(t)
    if bi is None or bi<180 or bi+120>=len(btc): continue

    btc_safe=btc[bi]["c"]>btc[bi-36]["c"]
    eth_safe=True
    if eth and t in maps["ETHUSDT"]:
        ei=maps["ETHUSDT"][t]
        if ei>=36:
            eth_safe=eth[ei]["c"]>eth[ei-36]["c"]

    markets=[]
    idx={}
    for sym,bars in data.items():
        i=maps[sym].get(t)
        if i is None or i<180 or i+120>=len(bars): continue
        m=ctx(sym,bars,i,btc_safe,eth_safe)
        if m:
            markets.append(m)
            idx[sym]=i

    ranked=ranker.rank(markets, top_n=TOPN)
    if not ranked:
        continue

    events += 1

    for r in ranked:
        sym=r.symbol
        i=idx[sym]
        signals += 1

        if active_until.get(sym,-1) > i:
            continue

        bars=data[sym]
        entry_i=find_pullback_entry(bars,i)
        if entry_i is None:
            continue

        trade=simulate_trade(bars,entry_i)
        if trade is None:
            continue

        pnl,hold,reason=trade
        results.append(pnl)
        holds.append(hold)
        reasons[reason]+=1
        entered += 1
        active_until[sym]=entry_i+hold+12

print("CYRUS UNIFIED - RANK -> PULLBACK -> RECLAIM TEST")
print(f"Symbols loaded: {len(data)}")
print(f"Ranking events: {events}")
print(f"Ranked candidates: {signals}")
print(f"Entered trades: {entered}")
print(f"Top N: {TOPN}")
print(f"Cost: {COST*100:.2f}%")
print()

if results:
    wins=sum(x>0 for x in results)
    avg=sum(results)/len(results)
    avg_hold=sum(holds)/len(holds)
    print(f"N={len(results)} WR={wins/len(results)*100:.1f}% NET_AVG={avg*100:+.3f}% PF={pf(results):.2f}")
    print(f"AVG_HOLD={avg_hold*5:.1f} min")
    print("EXITS:", dict(reasons))
else:
    print("NO TRADES")

print()
print("PASS GUIDE: PF > 1.20, positive NET_AVG, enough trades.")
