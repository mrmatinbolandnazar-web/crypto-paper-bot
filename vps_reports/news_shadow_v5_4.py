#!/usr/bin/env python3
# V5.4 News Intelligence Shadow - OBSERVATION ONLY.
# Reads recent V5.3 candidates, scores fresh public news, never trades.

import csv, html, os, re, xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from urllib.request import Request, urlopen

V53_CSV='expert_shadow_v5_3.csv'
OUT_TXT='news_shadow_v5_4_latest.txt'
OUT_CSV='news_shadow_v5_4.csv'
LOOKBACK_HOURS=18
V53_MAX_AGE_MINUTES=20
TIMEOUT=15

FEEDS=[
 ('FED','https://www.federalreserve.gov/feeds/press_all.xml',1.00),
 ('SEC','https://www.sec.gov/news/pressreleases.rss',1.00),
 ('COINDESK','https://www.coindesk.com/arc/outboundfeeds/rss/',0.82),
 ('COINTELEGRAPH','https://cointelegraph.com/rss',0.76),
 ('DECRYPT','https://decrypt.co/feed',0.76),
]

POS={
 'approval':.65,'approves':.65,'approved':.65,'launches':.35,'launch':.30,
 'integration':.30,'integrates':.30,'partnership':.30,'partners':.30,
 'adoption':.35,'upgrade':.25,'mainnet':.30,'inflows':.30,
 'record inflow':.45,'etf inflow':.45,'rate cut':.55,'cuts rates':.55,'dovish':.35,
}
NEG={
 'hack':-.90,'hacked':-.90,'exploit':-.90,'breach':-.85,'stolen':-.80,
 'vulnerability':-.65,'delist':-.75,'delisting':-.75,'lawsuit':-.55,
 'sues':-.55,'charged':-.55,'charges':-.50,'investigation':-.45,'probe':-.35,
 'bankruptcy':-.85,'insolvent':-.85,'collapse':-.75,'outage':-.50,
 'withdrawals halted':-.80,'halts withdrawals':-.80,'ban':-.65,
 'crackdown':-.50,'rate hike':-.55,'hikes rates':-.55,'hawkish':-.35,
 'liquidation':-.35,'liquidations':-.35,
}
CRYPTO_GLOBAL_TERMS=(
 'bitcoin','btc',
 'crypto market','crypto markets','cryptocurrency market',
 'digital asset market','digital asset markets',
 'stablecoin','stablecoins',
 'bitcoin etf','ethereum etf','crypto etf',
 'spot bitcoin etf','spot ethereum etf',
 'crypto regulation','crypto legislation'
)

MACRO_TERMS=(
 'interest rate','interest rates','rate cut','rate cuts',
 'rate hike','rate hikes','fomc','monetary policy',
 'inflation','cpi','pce','federal funds',
 'fed chair','federal reserve chair','jackson hole',
 'quantitative easing','quantitative tightening',
 'balance sheet','treasury yield','treasury yields'
)

SYSTEMIC_EXCHANGES=(
 'binance','coinbase','bybit','okx','kraken'
)

SYSTEMIC_TERMS=(
 'hack','hacked','exploit','breach','stolen',
 'outage','withdrawals halted','halts withdrawals',
 'bankruptcy','insolvent','collapse'
)

ALIASES={
 'BTC':('bitcoin','btc'),'ETH':('ethereum','ether','eth'),'BNB':('bnb','binance coin'),
 'SOL':('solana','sol'),'XRP':('xrp','ripple'),'DOGE':('dogecoin','doge'),
 'ADA':('cardano','ada'),'TRX':('tron','trx'),'LINK':('chainlink','link'),
 'AVAX':('avalanche','avax'),'SUI':('sui',),'DOT':('polkadot','dot'),
 'LTC':('litecoin','ltc'),'BCH':('bitcoin cash','bch'),'APT':('aptos','apt'),
 'ARB':('arbitrum','arb'),'OP':('optimism',),'PEPE':('pepe',),'UNI':('uniswap','uni'),
 'ATOM':('cosmos','atom'),'FIL':('filecoin','fil'),'HBAR':('hedera','hbar'),
 'XLM':('stellar','xlm'),'AAVE':('aave',),'INJ':('injective','inj'),
 'SEI':('sei',),'TIA':('celestia','tia'),'FET':('fetch.ai','fetch ai','fet'),
 'RENDER':('render','rndr'),'WIF':('dogwifhat','wif'),'BONK':('bonk',),
 'JUP':('jupiter','jup'),'ALGO':('algorand','algo'),'VET':('vechain','vet'),
 'CAKE':('pancakeswap','cake'),'ONDO':('ondo',),'TAO':('bittensor','tao'),
 'ENA':('ethena','ena'),'PENDLE':('pendle',),'WLD':('worldcoin','wld'),
 'STX':('stacks','stx'),'GRT':('the graph','grt'),'IMX':('immutable','imx'),
 'LDO':('lido','ldo'),'ONG':('ontology gas','ong'),'MOVR':('moonriver','movr'),
}

def now(): return datetime.now(timezone.utc)
def iso(): return now().isoformat()
def clamp(x,a=-1,b=1): return max(a,min(b,x))
def clean(x):
 x=html.unescape(x or ''); x=re.sub(r'<[^>]+>',' ',x); return re.sub(r'\s+',' ',x).strip()
def ptime(x):
 if not x:return None
 try:
  d=parsedate_to_datetime(x.strip());
  if d.tzinfo is None:d=d.replace(tzinfo=timezone.utc)
  return d.astimezone(timezone.utc)
 except: pass
 try:
  d=datetime.fromisoformat(x.strip().replace('Z','+00:00'))
  if d.tzinfo is None:d=d.replace(tzinfo=timezone.utc)
  return d.astimezone(timezone.utc)
 except:return None

def fetch(url):
 r=Request(url,headers={'User-Agent':'crypto-paper-bot-v5.4-news-shadow/1.0','Accept':'application/rss+xml, application/atom+xml, text/xml, */*'})
 with urlopen(r,timeout=TIMEOUT) as z:return z.read()
def lname(tag): return tag.split('}')[-1].lower()
def first(node,names):
 for c in node.iter():
  if lname(c.tag) in names and c.text:
   t=clean(c.text)
   if t:return t
 return ''
def parse_feed(src,rel,blob):
 root=ET.fromstring(blob); out=[]
 for n in root.iter():
  if lname(n.tag) not in ('item','entry'):continue
  title=first(n,{'title'}); desc=first(n,{'description','summary','content'})
  dt=ptime(first(n,{'pubdate','published','updated','date'}))
  if title:out.append({'source':src,'rel':rel,'title':title,'summary':desc,'published':dt})
  if len(out)>=40:break
 return out

def base(sym): return sym[:-4] if sym.upper().endswith('USDT') else sym.upper()

AMBIGUOUS_TICKERS={
 'LINK','OP','DOT','UNI','ATOM','FIL','RENDER','TRUMP'
}

SECURITY_NEGATIVE_TERMS={
 'hack','hacked','exploit','breach','stolen',
 'vulnerability','outage','withdrawals halted',
 'halts withdrawals','bankruptcy','insolvent'
}

RESOLUTION_PATTERNS=(
 r"\b(?:wasn['’]?t|was not|isn['’]?t|is not|not)\b.{0,18}\b(?:hacked|breached|exploited)\b",
 r"\bno\b.{0,20}\b(?:hack|breach|exploit|exploitation)\b",
 r"\b(?:patched|fixed|resolved|remediated)\b.{0,80}\b(?:before|prior to)\b.{0,40}\b(?:exploit|exploitation|attack)\b",
 r"\b(?:vulnerability|flaw|exploit)\b.{0,80}\b(?:patched|fixed|resolved|remediated)\b",
 r"\bno\b.{0,25}\b(?:funds|assets|money)\b.{0,25}\b(?:lost|stolen|drained)\b",
 r"\b(?:prevented|blocked|stopped|avoided|foiled)\b.{0,50}\b(?:exploit|attack|hack|breach)\b",
)

ACTUAL_COMPROMISE_PATTERNS=(
 r"\b(?:funds|assets|tokens|crypto|money)\b.{0,35}\b(?:stolen|drained|lost)\b",
 r"\b(?:attacker|attackers|hacker|hackers)\b.{0,45}\b(?:stole|drained|exploited)\b",
 r"\b(?:successfully|actively)\b.{0,25}\b(?:exploited|hacked|breached)\b",
 r"\bexploit(?:ed)?\b.{0,30}\b(?:in the wild|funds|assets|drain)\b",
)

BROAD_CRYPTO_MARKET_TERMS=(
 'crypto market','crypto markets','cryptocurrency market',
 'digital asset market','digital asset markets',
 'crypto regulation','crypto legislation',
 'digital asset regulation','digital asset legislation',
 'stablecoin regulation','stablecoin legislation',
)

BTC_MARKET_RE=(
 r"\bbitcoin\b.{0,45}\b(?:price|rises|rose|falls|fell|slides|slid|drops|dropped|"
 r"rallies|rally|surges|surged|plunges|plunged|steadies|selloff|"
 r"above|below|etf|inflows|outflows)\b"
)

def _boundary(text, token):
 return bool(re.search(r'\b'+re.escape(token.lower())+r'\b',text.lower()))

def security_resolved(text):
 t=text.lower()
 resolved=any(re.search(x,t,re.I) for x in RESOLUTION_PATTERNS)
 actual=any(re.search(x,t,re.I) for x in ACTUAL_COMPROMISE_PATTERNS)
 return resolved and not actual

def _has_unnegated(text, term):
 low=text.lower()
 found=False

 for m in re.finditer(re.escape(term.lower()),low):
  found=True
  prefix=low[max(0,m.start()-60):m.start()]

  if re.search(
   r"(?:\bno\b|\bnot\b|\bnever\b|\bwithout\b|"
   r"wasn['’]?t|isn['’]?t|aren['’]?t|weren['’]?t|didn['’]?t)"
   r"(?:\W+\w+){0,5}\W*$",
   prefix,
   re.I,
  ):
   continue

  return True

 return False if found else False

def _score_text(text, security_safe=False):
 t=(text or '').lower()
 s=0.0

 for k,v in POS.items():
  if k in t:
   s+=v

 for k,v in NEG.items():
  if k not in t:
   continue

  if security_safe and k in SECURITY_NEGATIVE_TERMS:
   continue

  if _has_unnegated(t,k):
   s+=v

 if security_safe:
  s+=0.10

 return clamp(s)

def impact(a):
 title=a.get('title','')
 summary=a.get('summary','')
 combined=title+' '+summary

 safe=security_resolved(combined)

 ts=_score_text(title,safe)
 ss=_score_text(summary,safe)

 if not summary:
  return ts

 # Headlines carry most of the meaning.
 # If headline is neutral but body contains a severe event,
 # let the summary still carry meaningful weight.
 if abs(ts)<.05 and abs(ss)>=.65:
  return clamp(ss*.70)

 return clamp(ts*.72 + ss*.28)

def trump_token_relevance(a):
 title=a.get('title','') or ''
 summary=a.get('summary','') or ''
 tl=title.lower()
 sl=summary.lower()

 # Explicit ticker notation is very strong evidence.
 if re.search(r'(?<![A-Z0-9])\$TRUMP(?![A-Z0-9])', title):
  return 1.00

 # Uppercase TRUMP in a crypto headline.
 if re.search(r'(?<![A-Z0-9])TRUMP(?![A-Z0-9])', title):
  if re.search(
   r'\b(token|coin|memecoin|meme coin|crypto|cryptocurrency|'
   r'price|trading|trades|market cap|holders|wallet|exchange|'
   r'binance|coinbase|solana)\b',
   tl,
   re.I
  ):
   return .98

 # Proper-name "Trump" is accepted only with nearby crypto context.
 crypto_after = re.search(
  r'\b(?:official\s+)?trump\b.{0,45}\b'
  r'(?:token|coin|memecoin|meme coin|crypto|cryptocurrency|'
  r'price|trading|market cap|holders)\b',
  tl,
  re.I
 )

 crypto_before = re.search(
  r'\b(?:token|coin|memecoin|meme coin|crypto|cryptocurrency)\b'
  r'.{0,45}\b(?:official\s+)?trump\b',
  tl,
  re.I
 )

 if crypto_after or crypto_before:
  return .95

 # Summary-only evidence must also explicitly describe the crypto asset.
 if (
  re.search(r'\$TRUMP\b', summary)
  or re.search(
   r'\btrump\b.{0,35}\b(?:token|coin|memecoin|meme coin|crypto)\b',
   sl,
   re.I
  )
  or re.search(
   r'\b(?:token|coin|memecoin|meme coin|crypto)\b.{0,35}\btrump\b',
   sl,
   re.I
  )
 ):
  return .62

 # A person, administration or political story is NOT token news.
 return 0.0


THIRD_PARTY_SECURITY_PRODUCTS=(
 'ledger','onekey','metamask','trezor','trust wallet',
 'phantom wallet','rabby','hardware wallet',
 'wallet app','browser extension'
)

DIRECT_PROTOCOL_TERMS=(
 'network','protocol','blockchain','mainnet',
 'consensus','validator','validators'
)

def third_party_product_incident(a,sym):
 b=base(sym)
 title=(a.get('title','') or '').lower()
 summary=(a.get('summary','') or '').lower()
 full=title+' '+summary

 severe=any(
  k in full
  for k in (
   'hack','hacked','exploit','exploited','attack',
   'breach','stolen','vulnerability'
  )
 )

 if not severe:
  return False

 if not any(x in full for x in THIRD_PARTY_SECURITY_PRODUCTS):
  return False

 aliases=list(ALIASES.get(b,()))
 names=[x.lower() for x in aliases if len(x)>=3]

 if not names:
  names=[b.lower()]

 # If the story explicitly says the asset's own network/protocol/
 # blockchain/mainnet is affected, it is direct asset news.
 for name in names:
  for ctx in DIRECT_PROTOCOL_TERMS:
   if re.search(
    r'\b'+re.escape(name)+r'\b.{0,35}\b'+re.escape(ctx)+r'\b',
    full,
    re.I
   ):
    return False

 # Otherwise a third-party wallet/app security incident should
 # not be treated as an asset/protocol emergency.
 return any(re.search(r'\b'+re.escape(name)+r'\b',full,re.I) for name in names)


def symbol_relevance(a,sym):
 b=base(sym)
 title=a.get('title','')
 summary=a.get('summary','')

 if b=='TRUMP':
  return trump_token_relevance(a)

 # Example: a Ledger "Ethereum app" exploit is a Ledger/app incident,
 # not an Ethereum-network exploit.
 if third_party_product_incident(a,sym):
  return .30

 title_low=title.lower()
 summary_low=summary.lower()

 aliases=ALIASES.get(b,())

 # Full asset/project name in headline = strongest evidence.
 for alias in aliases:
  al=alias.lower()

  if al==b.lower():
   continue

  if len(al)>=3 and _boundary(title_low,al):
   return 1.00

 # Ticker in headline. Ambiguous English words require uppercase ticker.
 if re.search(r'(?<![A-Z0-9])'+re.escape(b)+r'(?![A-Z0-9])',title):
  return .95

 if b not in AMBIGUOUS_TICKERS and len(b)>=3:
  if _boundary(title_low,b):
   return .88

 # Summary-only matches are intentionally strict.
 # One casual mention in a long article is NOT enough.
 for alias in aliases:
  al=alias.lower()

  if al==b.lower() or len(al)<4:
   continue

  count=len(re.findall(r'\b'+re.escape(al)+r'\b',summary_low))

  if count>=2:
   return .68

  if count==1 and _boundary(summary_low[:180],al):
   return .58

 ticker_hits=len(
  re.findall(
   r'(?<![A-Z0-9])'+re.escape(b)+r'(?![A-Z0-9])',
   summary
  )
 )

 if ticker_hits>=2:
  return .58

 return 0.0

def symmatch(a,sym):
 return symbol_relevance(a,sym)>=.55

def article_emergency(a,sym,score,relevance):
 if third_party_product_incident(a,sym):
  return False

 if relevance<.85:
  return False

 text=(a.get('title','')+' '+a.get('summary','')).lower()

 if security_resolved(text):
  return False

 severe=any(
  k in text
  for k in (
   'hack','hacked','exploit','breach','stolen',
   'bankruptcy','insolvent','delist','delisting',
   'halts withdrawals','withdrawals halted'
  )
 )

 return bool(severe and score<=-.45)


def fresh(dt):
 if dt is None:return .35
 h=max(0,(now()-dt).total_seconds()/3600)
 return 1 if h<=1 else .85 if h<=3 else .65 if h<=6 else .45 if h<=12 else .25 if h<=LOOKBACK_HOURS else 0

def globalnews(a):
 title=(a.get('title','') or '').lower()
 summary=(a.get('summary','') or '').lower()
 full=title+' '+summary

 # Macro policy can genuinely affect the whole crypto market.
 if any(k in full for k in MACRO_TERMS):
  return True

 # Explicitly broad crypto-market/regulatory stories.
 if any(k in full for k in BROAD_CRYPTO_MARKET_TERMS):
  return True

 # Bitcoin price / ETF / market-action stories can be market-wide,
 # but a narrow Bitcoin wallet/technical story is NOT automatically global.
 if re.search(BTC_MARKET_RE,title,re.I):
  return True

 # Systemic exchange incidents are global only when the exchange
 # and the severe event are both materially present.
 if (
  any(k in title for k in SYSTEMIC_EXCHANGES)
  and any(k in full for k in SYSTEMIC_TERMS)
 ):
  return True

 return False


def aggregate(ev):
 if not ev:return 0,0
 den=sum(w for _,w,_ in ev); num=sum(s*w for s,w,_ in ev)
 return (clamp(num/den),clamp(den/2.2,0,1)) if den else (0,0)
def verdict(s,c):
 if c<.18:return 'DATA_WEAK'
 if s>=.35:return 'POSITIVE_HIGH'
 if s>=.12:return 'POSITIVE'
 if s>-.12:return 'NEUTRAL'
 if s>-.35:return 'NEGATIVE'
 return 'NEGATIVE_HIGH'

def recent_v53():
 if not os.path.exists(V53_CSV):return []
 latest={}; n=now()
 with open(V53_CSV,newline='',encoding='utf-8') as f:
  for r in csv.DictReader(f):
   d=ptime(r.get('time_utc'))
   if not d:continue
   age=(n-d).total_seconds()/60
   if age<0 or age>V53_MAX_AGE_MINUTES:continue
   s=r.get('symbol','')
   if s and (s not in latest or d>latest[s][0]):latest[s]=(d,r)
 return [x[1] for x in latest.values()]

def ensure_csv():
 if os.path.exists(OUT_CSV):return
 with open(OUT_CSV,'w',newline='',encoding='utf-8') as f:
  csv.writer(f).writerow(['time_utc','symbol','technical_score','technical_pass','expert_score','expert_verdict','market_news_score','market_news_confidence','market_news_verdict','symbol_news_score','symbol_news_confidence','symbol_news_verdict','emergency_negative','matched_articles','shadow_action'])

def main():
 print('='*92);print('V5.4 NEWS INTELLIGENCE SHADOW - NO TRADE IMPACT');print('='*92)
 cutoff=now()-timedelta(hours=LOOKBACK_HOURS); articles=[]; status=[]
 for src,url,rel in FEEDS:
  try:
   x=[a for a in parse_feed(src,rel,fetch(url)) if a['published'] is None or a['published']>=cutoff]
   articles+=x; status.append((src,'OK',len(x)))
  except Exception as e:
   status.append((src,'ERROR',0)); print(f'{src:14} FEED_ERROR {e}')
 ded={}
 for a in articles:
  k=re.sub(r'\W+',' ',a['title'].lower()).strip()
  if k not in ded or a['rel']>ded[k]['rel']:ded[k]=a
 articles=list(ded.values())
 market=[]; top=[]
 for a in articles:
  s=impact(a); w=a['rel']*fresh(a['published'])
  if w and globalnews(a) and abs(s)>0:market.append((s,w,a)); top.append((abs(s)*w,s,a))
 ms,mc=aggregate(market); mv=verdict(ms,mc); cands=recent_v53(); ensure_csv()
 lines=['V5.4 NEWS INTELLIGENCE SHADOW',f'Updated UTC: {iso()}',f'Lookback: {LOOKBACK_HOURS}h | articles={len(articles)} | recent V5.3 candidates={len(cands)}',f'Market news: score={ms:+.2f} confidence={mc:.2f} verdict={mv}','Mode: SHADOW ONLY - V5.2/V5.3 unchanged.','', 'Sources: '+' | '.join(f'{s}:{st}({n})' for s,st,n in status),'']
 if not cands:lines.append('No recent V5.3 candidate for symbol-specific news.')
 for r in sorted(cands,key=lambda q:float(q.get('technical_score',0) or 0),reverse=True):
  sym=r['symbol']; ev=[]; matched=[]; emergency=False
  for a in articles:
   rel=symbol_relevance(a,sym)
   if rel<.55:continue
   s=impact(a)
   w=a['rel']*fresh(a['published'])*rel
   matched.append((s,w,a,rel))
   if w and abs(s)>0:ev.append((s,w,a))
   if article_emergency(a,sym,s,rel):emergency=True
  ss,sc=aggregate(ev); sv=verdict(ss,sc)
  act='WOULD_EMERGENCY_VETO' if emergency else 'WOULD_CAUTION' if sv in ('NEGATIVE','NEGATIVE_HIGH') else 'WOULD_SUPPORT' if sv in ('POSITIVE','POSITIVE_HIGH') else 'WOULD_MARKET_CAUTION' if mv=='NEGATIVE_HIGH' else 'OBSERVE'
  tech=float(r.get('technical_score',0) or 0); expert=float(r.get('expert_score',0) or 0)
  with open(OUT_CSV,'a',newline='',encoding='utf-8') as f:
   csv.writer(f).writerow([iso(),sym,f'{tech:.4f}',r.get('technical_pass','N'),f'{expert:.4f}',r.get('expert_verdict',''),f'{ms:.4f}',f'{mc:.4f}',mv,f'{ss:.4f}',f'{sc:.4f}',sv,'Y' if emergency else 'N',len(matched),act])
  lines.append(f"{sym:12} tech={tech:.2f} expert={expert:+.2f} {r.get('expert_verdict','')} | news={ss:+.2f} conf={sc:.2f} {sv} | matched={len(matched)} | {act}")
  for s,w,a,rel in sorted(matched,key=lambda z:abs(z[0])*z[1],reverse=True)[:2]:
   dt=a['published'].isoformat() if a['published'] else 'time_unknown'; lines.append(f"  [{a['source']}] {s:+.2f} rel={rel:.2f} {dt} | {a['title'][:150]}")
 top.sort(reverse=True,key=lambda z:z[0])
 if top:
  lines+=['','Top market-impact headlines:']
  for _,s,a in top[:8]:
   dt=a['published'].isoformat() if a['published'] else 'time_unknown'; lines.append(f"  [{a['source']}] {s:+.2f} {dt} | {a['title'][:160]}")
 text='\n'.join(lines)+'\n'; open(OUT_TXT,'w',encoding='utf-8').write(text); print('\n'+text);print('Saved:',OUT_TXT);print('Saved:',OUT_CSV)

if __name__=='__main__':main()
