from dataclasses import dataclass


@dataclass
class StrategyChoice:
    strategy: str
    enabled: bool
    reason: str


class StrategySelector:
    def select(self, market):
        regime = getattr(market, "regime", "UNKNOWN")

        if regime == "RISK_OFF":
            return StrategyChoice("CASH", False, "Risk-off market")

        if regime == "HIGH_VOL":
            return StrategyChoice("CASH", False, "Abnormal volatility")

        if regime == "TREND_UP":
            return StrategyChoice(
                "TREND_PULLBACK",
                True,
                "Bull trend: use trend pullback first"
            )

        if regime == "RANGE":
            return StrategyChoice(
                "RANGE_MEAN_REVERSION",
                True,
                "Range market: use mean reversion"
            )

        return StrategyChoice("CASH", False, "Unknown regime")
