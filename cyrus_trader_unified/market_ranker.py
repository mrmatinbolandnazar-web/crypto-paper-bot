from dataclasses import dataclass


@dataclass
class RankedMarket:
    symbol: str
    score: float
    reason: str


class MarketRanker:
    def score(self, market):
        if getattr(market, "regime", "") in ("RISK_OFF", "HIGH_VOL"):
            return RankedMarket(
                getattr(market, "symbol", ""),
                -999.0,
                "blocked_regime"
            )

        score = 0.0
        reasons = []

        if getattr(market, "trend_1h", False):
            score += 3.0
            reasons.append("1h_trend")

        if getattr(market, "trend_15m", False):
            score += 2.0
            reasons.append("15m_trend")

        m15 = float(getattr(market, "tf15_mom3", 0.0))
        m1h = float(getattr(market, "tf1h_mom3", 0.0))
        s15 = float(getattr(market, "tf15_fast_slope", 0.0))
        s1h = float(getattr(market, "tf1h_fast_slope", 0.0))
        vol = float(getattr(market, "volatility", 0.0))

        score += max(-2.0, min(4.0, m15 * 120.0))
        score += max(-2.0, min(4.0, m1h * 80.0))
        score += max(-1.5, min(2.5, s15 * 500.0))
        score += max(-1.5, min(2.5, s1h * 300.0))

        if getattr(market, "btc_safe", False):
            score += 0.75
            reasons.append("btc_safe")

        if getattr(market, "eth_safe", False):
            score += 0.50
            reasons.append("eth_safe")

        if 0.003 <= vol <= 0.02:
            score += 0.75
            reasons.append("usable_volatility")
        elif vol > 0.03:
            score -= 1.0
            reasons.append("excess_volatility")

        return RankedMarket(
            symbol=getattr(market, "symbol", ""),
            score=round(score, 6),
            reason=",".join(reasons) if reasons else "none"
        )

    def rank(self, markets, top_n=3):
        ranked = [self.score(m) for m in markets]
        ranked = [x for x in ranked if x.score > -900]
        ranked.sort(key=lambda x: x.score, reverse=True)
        return ranked[:top_n]
