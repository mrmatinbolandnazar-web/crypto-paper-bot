from typing import Any, Dict, Optional

import expert_shadow_v5_3 as v53
import crowd_psychology_v5_5 as v55
from cyrus_trader_unified.news_adapter import CyrusNewsAdapter


class CyrusIntelligenceSources:
    """
    CYRUS V7 intelligence data gateway.

    LIVE:
      - V5.3 Expert/Futures is queried live.
      - V5.5 Crowd Psychology is queried live.
      - V5.4 News is supplied through news_data until its adapter is wired.

    BACKTEST:
      - Never fetch current/live intelligence.
      - Historical snapshots must be supplied explicitly.
      This prevents future/current data contamination of OOS tests.
    """

    def __init__(self, mode: str = "live"):
        mode = str(mode).lower().strip()
        if mode not in ("live", "backtest"):
            raise ValueError("mode must be 'live' or 'backtest'")
        self.mode = mode
        self.news = CyrusNewsAdapter() if mode == "live" else None

    def get(
        self,
        symbol: str,
        analysis: Optional[Dict[str, Any]] = None,
        news_data: Optional[Dict[str, Any]] = None,
        historical_expert: Optional[Dict[str, Any]] = None,
        historical_crowd: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Dict[str, Any]]:

        analysis = analysis or {}

        if self.mode == "backtest":
            return {
                "expert": historical_expert or {},
                "news": news_data or {},
                "crowd": historical_crowd or {},
            }

        expert = {}
        crowd = {}

        try:
            expert = v53.expert_snapshot(symbol, analysis) or {}
        except Exception as e:
            expert = {
                "verdict": "DATA_WEAK",
                "coverage": 0.0,
                "_error": str(e),
            }

        try:
            spot = v55.spot_snapshot(symbol)
            crowd = v55.psychology_snapshot(symbol, spot) or {}
        except Exception as e:
            crowd = {
                "verdict": "NEUTRAL",
                "confidence": "DATA_WEAK",
                "coverage": 0,
                "_error": str(e),
            }

        news = news_data or {}
        if not news:
            try:
                news = self.news.snapshot(symbol) if self.news else {}
            except Exception as e:
                news = {
                    "verdict": "DATA_WEAK",
                    "confidence": 0.0,
                    "_error": str(e),
                }

        return {
            "expert": expert,
            "news": news,
            "crowd": crowd,
        }


if __name__ == "__main__":
    g = CyrusIntelligenceSources(mode="backtest")
    print(g.get("BTCUSDT"))
