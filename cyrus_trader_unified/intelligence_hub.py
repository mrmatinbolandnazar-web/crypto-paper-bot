from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class IntelligenceDecision:
    verdict: str
    risk_multiplier: float
    reasons: List[str] = field(default_factory=list)
    expert: Dict[str, Any] = field(default_factory=dict)
    news: Dict[str, Any] = field(default_factory=dict)
    crowd: Dict[str, Any] = field(default_factory=dict)


class CyrusIntelligenceHub:
    """
    CYRUS V7 Unified Intelligence Gate

    V5.3 Expert/Futures  -> confirmation / professional-flow risk
    V5.4 News            -> event/news risk
    V5.5 Crowd Psychology-> FOMO/trap/panic risk

    These layers NEVER create a BUY.
    They only ALLOW, CAUTION or BLOCK an existing technical setup.
    """

    @staticmethod
    def _num(x, default=0.0):
        try:
            return float(x)
        except Exception:
            return default

    @staticmethod
    def _confidence(x):
        if isinstance(x, (int, float)):
            return max(0.0, min(1.0, float(x)))
        s = str(x or "").upper()
        if s == "HIGH":
            return 1.0
        if s == "MEDIUM":
            return 0.65
        if s in ("LOW", "DATA_WEAK"):
            return 0.25
        return 0.5

    def evaluate(self, expert=None, news=None, crowd=None):
        expert = expert or {}
        news = news or {}
        crowd = crowd or {}

        reasons = []
        caution = False
        block = False

        # ---------- V5.3 EXPERT / FUTURES ----------
        expert_score = self._num(expert.get("expert_score"), 5.0)
        expert_cov = self._confidence(expert.get("coverage"))
        expert_verdict = str(expert.get("verdict", "")).upper()

        if expert_cov >= 0.50:
            if expert_score < 3.0:
                block = True
                reasons.append("EXPERT_FLOW_VERY_WEAK")
            elif expert_score < 4.5:
                caution = True
                reasons.append("EXPERT_FLOW_WEAK")

        if any(x in expert_verdict for x in ("BLOCK", "AVOID", "NEGATIVE_HIGH")):
            block = True
            reasons.append("EXPERT_VERDICT_BLOCK")

        # ---------- V5.4 NEWS ----------
        news_score = self._num(news.get("score", news.get("news_score")), 0.0)
        news_conf = self._confidence(news.get("confidence", news.get("coverage")))
        news_verdict = str(news.get("verdict", "")).upper()

        if news.get("emergency") is True:
            block = True
            reasons.append("NEWS_EMERGENCY")
        elif news_verdict == "NEGATIVE_HIGH" and news_conf >= 0.35:
            block = True
            reasons.append("NEWS_NEGATIVE_HIGH")
        elif news_verdict == "NEGATIVE" and news_conf >= 0.35:
            caution = True
            reasons.append("NEWS_NEGATIVE")
        elif news_score <= -0.35 and news_conf >= 0.35:
            block = True
            reasons.append("NEWS_SCORE_HIGH_RISK")
        elif news_score <= -0.12 and news_conf >= 0.35:
            caution = True
            reasons.append("NEWS_SCORE_CAUTION")

        # ---------- V5.5 CROWD PSYCHOLOGY ----------
        crowd_verdict = str(crowd.get("verdict", "")).upper()
        crowd_conf = self._confidence(crowd.get("confidence"))
        temptation = self._num(crowd.get("temptation"))
        trap_risk = self._num(crowd.get("trap_risk"))
        squeeze = self._num(crowd.get("squeeze_score"))
        panic = self._num(crowd.get("panic_score"))

        if crowd_verdict == "DO_NOT_CHASE_LONG_TRAP":
            block = True
            reasons.append("CROWD_LONG_TRAP")
        elif crowd_verdict == "CROWD_TRAP_RISK":
            caution = True
            reasons.append("CROWD_TRAP_RISK")
        elif crowd_verdict == "FOMO_BUILDING":
            caution = True
            reasons.append("FOMO_BUILDING")
        elif crowd_verdict in ("SHORT_SQUEEZE_WATCH", "PANIC_EXHAUSTION_WATCH"):
            caution = True
            reasons.append(crowd_verdict)

        if crowd_conf >= 0.65 and trap_risk >= 0.72:
            block = True
            reasons.append("HIGH_TRAP_RISK")
        elif crowd_conf >= 0.65 and trap_risk >= 0.62:
            caution = True
            reasons.append("ELEVATED_TRAP_RISK")

        if temptation >= 0.70:
            caution = True
            reasons.append("HIGH_TEMPTATION")

        # ---------- FINAL GATE ----------
        if block:
            verdict = "BLOCK"
            risk_multiplier = 0.0
        elif caution:
            verdict = "CAUTION"
            risk_multiplier = 0.50
        else:
            verdict = "ALLOW"
            risk_multiplier = 1.0

        return IntelligenceDecision(
            verdict=verdict,
            risk_multiplier=risk_multiplier,
            reasons=reasons,
            expert=expert,
            news=news,
            crowd=crowd,
        )


if __name__ == "__main__":
    hub = CyrusIntelligenceHub()
    print(hub.evaluate(
        expert={"expert_score": 6.5, "coverage": 0.8, "verdict": "READY"},
        news={"score": 0.0, "confidence": 0.8, "verdict": "NEUTRAL"},
        crowd={
            "temptation": 0.3,
            "trap_risk": 0.2,
            "squeeze_score": 0.2,
            "panic_score": 0.2,
            "verdict": "NEUTRAL",
            "confidence": "HIGH",
        },
    ))
