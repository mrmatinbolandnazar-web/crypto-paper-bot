from cyrus_trader_v7.market_engine import CyrusMarketEngine
from cyrus_trader_v7.signal_engine import CyrusSignalEngine
from cyrus_trader_v7.trade_validator import CyrusTradeValidator
from cyrus_trader_v7.risk_engine import CyrusRiskEngine
from cyrus_trader_v7.execution_engine import CyrusExecutionEngine
from cyrus_trader_v7.position_manager import CyrusPositionManager
from cyrus_trader_v7.portfolio_protector import CyrusPortfolioProtector
from cyrus_trader_v7.intelligence_hub import CyrusIntelligenceHub
from cyrus_trader_v7.intelligence_sources import CyrusIntelligenceSources


class CyrusTraderV7:
    """
    Central V7 Unified decision pipeline.

    Market
      -> Signal
      -> Validator
      -> Portfolio Protection
      -> Risk
      -> Execution

    Open positions are handled separately by PositionManager.
    """

    def __init__(self, mode: str = "live"):
        self.market = CyrusMarketEngine()
        self.signal = CyrusSignalEngine()
        self.validator = CyrusTradeValidator()
        self.risk = CyrusRiskEngine()
        self.execution = CyrusExecutionEngine()
        self.positions = CyrusPositionManager()
        self.protector = CyrusPortfolioProtector()
        self.intelligence = CyrusIntelligenceHub()
        self.intel_sources = CyrusIntelligenceSources(mode=mode)

    def evaluate_entry(
        self,
        symbol: str,
        equity: float,
        portfolio_state: dict,
        time_utc: str,
        expert_data: dict = None,
        news_data: dict = None,
        crowd_data: dict = None,
    ):
        market = self.market.evaluate(symbol)

        if market.regime != "TREND_UP":
            return {
                "action": "SKIP",
                "stage": "MARKET",
                "reason": market.regime,
                "market": market,
            }

        signal = self.signal.find_signal(symbol, market)

        if signal is None:
            return {
                "action": "SKIP",
                "stage": "SIGNAL",
                "reason": "NO_SETUP",
                "market": market,
            }

        src = self.intel_sources.get(symbol, analysis={"mom15": signal.metadata.get("candle_move", 0.0)}) if expert_data is None and news_data is None and crowd_data is None else {"expert": expert_data or {}, "news": news_data or {}, "crowd": crowd_data or {}}
        intel = self.intelligence.evaluate(expert=src.get("expert", {}), news=src.get("news", {}), crowd=src.get("crowd", {}))
        if intel.verdict == "BLOCK":
            return {"action": "SKIP", "stage": "INTELLIGENCE", "reason": ",".join(intel.reasons), "market": market, "signal": signal, "intelligence": intel}

        if not self.validator.validate(signal, market):
            return {
                "action": "SKIP",
                "stage": "VALIDATOR",
                "reason": "SIGNAL_REJECTED",
                "market": market,
                "signal": signal,
            }

        protected, protection_reason = self.protector.check(
            portfolio_state,
            time_utc,
        )

        if not protected:
            return {
                "action": "SKIP",
                "stage": "PROTECTOR",
                "reason": protection_reason,
                "market": market,
                "signal": signal,
            }

        risk = self.risk.evaluate(
            signal,
            equity,
            portfolio_state,
        )

        if not risk.approved:
            return {
                "action": "SKIP",
                "stage": "RISK",
                "reason": risk.reason,
                "market": market,
                "signal": signal,
                "risk": risk,
            }

        position = self.execution.open_position(
            signal,
            risk,
            portfolio_state,
            time_utc,
        )

        if position is None:
            return {
                "action": "SKIP",
                "stage": "EXECUTION",
                "reason": "OPEN_FAILED",
                "market": market,
                "signal": signal,
                "risk": risk,
            }

        return {
            "action": "OPEN",
            "stage": "EXECUTION",
            "reason": risk.reason,
            "market": market,
            "signal": signal,
            "risk": risk,
            "position": position,
        }

    def evaluate_position(
        self,
        position: dict,
        age_minutes: float,
    ):
        return self.positions.manage(
            position=position,
            symbol=position["symbol"],
            age_minutes=age_minutes,
        )

    def close_position(
        self,
        position: dict,
        raw_exit_price: float,
        reason: str,
        time_utc: str,
        expert_data: dict = None,
        news_data: dict = None,
        crowd_data: dict = None,
    ):
        return self.execution.close_position(
            position,
            raw_exit_price,
            reason,
            time_utc,
        )


if __name__ == "__main__":
    bot = CyrusTraderV6()

    print("CYRUS TRADER V6 CENTRAL ENGINE OK")
    print(
        "Market -> Signal -> Validator -> "
        "Protection -> Risk -> Execution -> Position"
    )
