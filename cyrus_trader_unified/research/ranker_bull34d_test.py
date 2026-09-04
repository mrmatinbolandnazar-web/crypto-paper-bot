import json, math
from pathlib import Path
from types import SimpleNamespace
from collections import defaultdict
from cyrus_trader_unified.market_ranker import MarketRanker

CACHE = Path("/opt/crypto-paper-bot/.backtest_cache_v5_2")
START_MS = 1784901900000
END_MS   = 1787839500000
COST = 0.0026
STEP = 12                   # rank once per hour on 5m bars
HORIZONS = {24:"2H",48:"4H",96:"8H"}

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

    # 15m-equivalent trend from 5m data
    e15f=ema(c[i-119:i+1],36)
    e15s=ema(c[i-179:i+1],72)
    e15f_prev=ema(c[i-122:i-2],36)

    # 1h-equivalent trend / momentum
    mom15=c[i]/c[i-9]-1          # ~45m = 3 x 15m
    mom1h=c[i]/c[i-36]-1         # ~3h = 3 x 1h
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

def pf(v):
    p=sum(x for x in v if x>0)
    n=abs(sum(x for x in v if x<0))
    return p/n if n else float("inf")

files=list(CACHE.glob("*_5m_20260525_20260827.json"))
symbols=sorted({p.name.split("_5m_")[0] for p in files})
data={s:load(s) for s in symbols}
data={s:b for s,b in data.items() if b}

btc=data.get("BTCUSDT")
eth=data.get("ETHUSDT")
if not btc:
    raise SystemExit("BTC DATA MISSING")

# align all data by timestamp
maps={s:{x["t"]:j for j,x in enumerate(b)} for s,b in data.items()}
btc_map=maps["BTCUSDT"]
times=[x["t"] for x in btc if START_MS<=x["t"]<=END_MS]

ranker=MarketRanker()
res={1:{h:[] for h in HORIZONS},3:{h:[] for h in HORIZONS}}
alpha={1:{h:[] for h in HORIZONS},3:{h:[] for h in HORIZONS}}
events=0

for k,t in enumerate(times):
    if k%STEP: continue
    bi=btc_map.get(t)
    if bi is None or bi<180 or bi+96>=len(btc): continue

    btc_safe=btc[bi]["c"]>btc[bi-36]["c"]
    eth_safe=True
    if eth and t in maps["ETHUSDT"]:
        ei=maps["ETHUSDT"][t]
        if ei>=36: eth_safe=eth[ei]["c"]>eth[ei-36]["c"]

    markets=[]
    idx={}
    for s,b in data.items():
        i=maps[s].get(t)
        if i is None or i<180 or i+96>=len(b): continue
        m=ctx(s,b,i,btc_safe,eth_safe)
        if m:
            markets.append(m); idx[s]=i

    ranked=ranker.rank(markets,top_n=3)
    if not ranked: continue
    events+=1

    for topn in (1,3):
        picks=ranked[:topn]
        for h in HORIZONS:
            vals=[]; alphas=[]
            btc_ret=btc[bi+h]["c"]/btc[bi]["c"]-1
            for r in picks:
                b=data[r.symbol]; i=idx[r.symbol]
                net=b[i+h]["c"]/b[i]["c"]-1-COST
                vals.append(net)
                alphas.append(net-btc_ret)
            res[topn][h].append(sum(vals)/len(vals))
            alpha[topn][h].append(sum(alphas)/len(alphas))

print("CYRUS UNIFIED MARKET RANKER - BULL 34D")
print(f"Symbols loaded: {len(data)}")
print(f"Ranking events: {events}")
print(f"Cost: {COST*100:.2f}% | Ranking interval: 1 hour")
print()

for n in (1,3):
    print("="*72)
    print(f"TOP {n}")
    for h,label in HORIZONS.items():
        v=res[n][h]; a=alpha[n][h]
        wr=sum(x>0 for x in v)/len(v)*100 if v else 0
        avg=sum(v)/len(v) if v else 0
        avga=sum(a)/len(a) if a else 0
        print(f"{label:>2} | N={len(v):4d} WR={wr:5.1f}% NET_AVG={avg*100:+.3f}% PF={pf(v):.2f} ALPHA_vs_BTC={avga*100:+.3f}%")

print()
print("PASS GUIDE: PF > 1.20, positive NET_AVG, positive alpha, enough observations.")
