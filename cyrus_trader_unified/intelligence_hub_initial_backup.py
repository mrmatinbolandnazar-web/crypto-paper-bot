from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class IntelligenceDecision:
    verdict: str
    score: float
    confidence: float
    reasons: List[str] = field(default_factory=list)
    expert: Dict[str, Any] = field(default_factory=dict)
    news: Dict[str, Any] = field(default_factory=dict)
    crowd: Dict[str, Any] = field(default_factory=dict)


class CyrusIntelligenceHub:
    """
    V7 intelligence aggregation layer.

    Roles:
    - V5.3 Expert/Futures: professional-flow confirmation/risk
    - V5.4 News: event/emergency/news risk
    - V5.5 Crowd Psychology: FOMO/trap/panic/crowd risk

    This module does NOT generate BUY signals.
    It only confirms, cautions, or blocks an existing technical setup.
    """

    def __init__(self):
        self.expert_weight = 0.35
        self.news_weight = 0.25
        self.crowd_weight = 0.40

    @staticmethod
    def _norm_score(value, default=0.5):
        try:
            x = float(value)
        except Exception:
            return default

        if -1.0 <= x <= 1.0:
            return (x + 1.0) / 2.0

        if 0.0 <= x <= 10.0:
            return x / 10.0

        if 0.0 <= x <= 100.0:
            return x / 100.0

        return default

    @staticmethod
    def _confidence(data):
        if not isinstance(data, dict):
            return 0.0

        for key in ("confidence", "coverage"):
            if key in data:
                try:
                    x = float(data[key])
                    if x > 1.0:
                        x /= 100.0
                    return max(0.0, min(1.0, x))
                except Exception:
                    pass

        return 0.5

    @staticmethod
    def _contains_blocking_text(data):
        text = str(data).upper()
        hard_terms = (
            "EMERGENCY",
            "CRITICAL",
            "SCAM",
            "EXPLOIT",
            "HACK",
            "SECURITY INCIDENT",
            "EXTREME FOMO",
            "TRAP",
            "PANIC",
        )
        return any(term in text for term in hard_terms)

    def evaluate(self, expert=None, news=None, crowd=None):
        expert = expert or {}
        news = news or {}
        crowd = crowd or {}

        reasons = []

        expert_score = self._norm_score(
            expert.get("score", expert.get("expert_score", 0.5))
            if isinstance(expert, dict) else 0.5
        )

        news_score = self._norm_score(
            news.get("score", news.get("news_score", 0.5))
            if isinstance(news, dict) else 0.5
        )

        crowd_score = self._norm_score(
            crowd.get("score", crowd.get("psychology_score", 0.5))
            if isinstance(crowd, dict) else 0.5
        )

        expert_conf = self._confidence(expert)
        news_conf = self._confidence(news)
        crowd_conf = self._confidence(crowd)

        confidence = (
            expert_conf * self.expert_weight
            + news_conf * self.news_weight
            + crowd_conf * self.crowd_weight
        )

        score = (
            expert_score * self.expert_weight
            + news_score * self.news_weight
            + crowd_score * self.crowd_weight
        )

        hard_block = False

        if self._contains_blocking_text(news):
            hard_block = True
            reasons.append("NEWS_RISK")

        if self._contains_blocking_text(crowd):
            hard_block = True
            reasons.append("CROWD_RISK")

        if expert_score < 0.30 and expert_conf >= 0.50:
            reasons.append("EXPERT_FLOW_WEAK")

        if crowd_score < 0.30 and crowd_conf >= 0.50:
            reasons.append("CROWD_SETUP_WEAK")

        if hard_block:
            verdict = "BLOCK"
        elif score < 0.42:
            verdict = "BLOCK"
            reasons.append("LOW_COMBINED_SCORE")
        elif score < 0.58:
            verdict = "CAUTION"
            reasons.append("MIXED_INTELLIGENCE")
        else:
            verdict = "ALLOW"

        return IntelligenceDecision(
            verdict=verdict,
            score=round(score, 4),
            confidence=round(confidence, 4),
            reasons=reasons,
            expert=expert,
            news=news,
            crowd=crowd,
        )


if __name__ == "__main__":
    hub = CyrusIntelligenceHub()
    print(hub.evaluate())
