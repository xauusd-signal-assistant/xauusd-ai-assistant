from .config import settings
from .models import TradingViewAlert, SignalDecision
from .session import trading_window_status

def wait(reason: str, source: str = "risk_gate", confidence: int = 95):
    return SignalDecision(action="WAIT", execution_timeframe="None", confidence=confidence,
        reason=reason, invalidation="Reassess after the condition clears", source=source)

def rules_decision(alert: TradingViewAlert):
    allowed, reason = trading_window_status(alert.timestamp)
    if not allowed: return wait(reason)
    max_loss = settings.demo_balance_gbp * settings.max_daily_loss_percent / 100
    if alert.daily_pnl <= -max_loss: return wait("Daily loss limit reached")
    if alert.open_positions >= 1: return wait("An XAUUSD trade is already open")
    if alert.spread is not None and alert.spread > alert.atr * 0.12: return wait("Spread is too high")
    if alert.setup == "none": return wait("No confirmed setup")
    if alert.adx < 20: return wait("Market trend is too weak")

    direction = "bullish" if alert.setup == "long" else "bearish"
    action = "BUY" if direction == "bullish" else "SELL"
    if any(t != direction for t in [alert.trend_15m, alert.trend_1h, alert.trend_4h]):
        return wait("15m, 1H and 4H do not align", "rules", 88)
    ema_ok = alert.price > alert.ema20 > alert.ema50 if action == "BUY" else alert.price < alert.ema20 < alert.ema50
    if not ema_ok: return wait("EMA structure does not confirm", "rules", 86)
    momentum_ok = 53 <= alert.rsi <= 68 if action == "BUY" else 32 <= alert.rsi <= 47
    if not momentum_ok: return wait("Momentum is weak or stretched", "rules", 84)

    if alert.trend_1m == direction and alert.trend_5m == direction and alert.adx >= 25:
        chart, mult, reason, confidence = "1 Minute", 1.15, "Precision entry; trends aligned", 91
    else:
        chart, mult, reason, confidence = "5 Minute", 1.35, "Strong multi-timeframe trend", 88

    stop_distance = alert.atr * mult
    target_distance = stop_distance * settings.min_risk_reward
    stop = alert.price - stop_distance if action == "BUY" else alert.price + stop_distance
    target = alert.price + target_distance if action == "BUY" else alert.price - target_distance
    return SignalDecision(action=action, execution_timeframe=chart, confidence=confidence,
        entry=round(alert.price, 2), stop_loss=round(stop, 2), take_profit=round(target, 2),
        risk_reward=settings.min_risk_reward, reason=reason,
        invalidation=f"Invalid if price reaches {stop:.2f}", source="rules")
