from cyrus_trader_v7.architecture import TradeSignal, MarketContext


class CyrusTradeValidator:
    def validate(
        self,
        signal: TradeSignal,
        market: MarketContext
    ) -> bool:

        if signal.side != "BUY":
            return False

        if market.regime != "TREND_UP":
            return False

        # Higher-timeframe structure must still agree.
        if not (
            market.trend_15m
            and market.trend_1h
        ):
            return False

        # At least one benchmark must be healthy.
        # If both BTC and ETH are weak, reject the trade.
        if not (market.btc_safe or market.eth_safe):
            return False

        md = signal.metadata

        risk_pct = float(md.get("risk_pct", 999))
        extension = float(md.get("extension_pct", 999))
        atr_pct = float(md.get("atr_pct", 999))
        candle_move = float(md.get("candle_move", 999))

        # Structural risk window.
        if not 0.0020 <= risk_pct <= 0.0120:
            return False

        # Entry should still be near value, not chased.
        if not 0.0 <= extension <= 0.0035:
            return False

        # Reject dead markets and violent volatility.
        if not 0.0015 <= atr_pct <= 0.0120:
            return False

        # Reclaim candle must be meaningful,
        # but not an explosive late-entry candle.
        if not 0.0002 <= candle_move <= 0.0070:
            return False

        # Invalidation must be below entry.
        if signal.invalidation_price >= signal.entry_price:
            return False

        return True


if __name__ == "__main__":
    print("CYRUS V6 TRADE VALIDATOR OK")
