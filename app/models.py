from typing import Literal
from pydantic import BaseModel, Field, field_validator

Trend = Literal["bullish", "bearish", "neutral"]

class TradingViewAlert(BaseModel):
    secret: str
    alert_id: str = Field(min_length=4, max_length=160)
    symbol: str
    timeframe: str
    timestamp: int
    price: float = Field(gt=0)
    ema20: float = Field(gt=0)
    ema50: float = Field(gt=0)
    rsi: float = Field(ge=0, le=100)
    atr: float = Field(gt=0)
    adx: float = Field(ge=0)
    trend_1m: Trend
    trend_5m: Trend
    trend_15m: Trend
    trend_1h: Trend
    trend_4h: Trend
    setup: Literal["long", "short", "none"]
    spread: float | None = Field(default=None, ge=0)
    daily_pnl: float = 0.0
    open_positions: int = Field(default=0, ge=0)

    @field_validator("symbol")
    @classmethod
    def only_xauusd(cls, value: str) -> str:
        if "XAUUSD" not in value.upper().replace("/", ""):
            raise ValueError("XAUUSD only")
        return value

class SignalDecision(BaseModel):
    action: Literal["BUY", "SELL", "WAIT"]
    execution_timeframe: Literal["1 Minute", "5 Minute", "None"]
    confidence: int = Field(ge=0, le=100)
    entry: float | None = None
    stop_loss: float | None = None
    take_profit: float | None = None
    risk_reward: float | None = None
    demo_lot: float | None = None
    live_lot: float | None = None
    reason: str
    invalidation: str
    source: Literal["rules", "openai", "risk_gate", "fallback"]
