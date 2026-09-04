"""
CYRUS Trader V6
Clean modular architecture.

Flow:
MarketEngine
    -> SignalEngine
    -> TradeValidator
    -> RiskEngine
    -> ExecutionEngine
    -> PositionManager
    -> PortfolioProtector

No V5 score logic.
No regime-dependent aggressive sizing.
No live trading yet.
"""

from dataclasses import dataclass, field
from typing import Optional, Dict, Any


@dataclass
class MarketContext:
    symbol: str
    regime: str
    trend_5m: bool
    trend_15m: bool
    trend_1h: bool
    volatility: float
    btc_safe: bool
    eth_safe: bool
    tf15_mom3: float = 0.0
    tf15_fast_slope: float = 0.0
    tf1h_mom3: float = 0.0
    tf1h_fast_slope: float = 0.0


@dataclass
class TradeSignal:
    symbol: str
    side: str
    setup: str
    entry_price: float
    invalidation_price: float
    confidence: float
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RiskDecision:
    approved: bool
    spend_usdt: float
    max_loss_usdt: float
    reason: str


class MarketEngine:
    def evaluate(self, symbol: str) -> MarketContext:
        raise NotImplementedError


class SignalEngine:
    def find_signal(
        self,
        symbol: str,
        market: MarketContext
    ) -> Optional[TradeSignal]:
        raise NotImplementedError


class TradeValidator:
    def validate(
        self,
        signal: TradeSignal,
        market: MarketContext
    ) -> bool:
        raise NotImplementedError


class RiskEngine:
    def evaluate(
        self,
        signal: TradeSignal,
        equity: float,
        portfolio_state: Dict[str, Any]
    ) -> RiskDecision:
        raise NotImplementedError


class ExecutionEngine:
    def open_position(
        self,
        signal: TradeSignal,
        risk: RiskDecision
    ):
        raise NotImplementedError


class PositionManager:
    def manage(
        self,
        position: Dict[str, Any],
        market: MarketContext
    ):
        raise NotImplementedError


class PortfolioProtector:
    def allow_new_trade(
        self,
        portfolio_state: Dict[str, Any]
    ) -> bool:
        raise NotImplementedError


if __name__ == "__main__":
    print("CYRUS TRADER V6 ARCHITECTURE OK")
    print("Market -> Signal -> Validator -> Risk -> Execution -> Position -> Protection")
