from app.models import TradingViewAlert
from app.risk import rules_decision


def base_alert(**overrides):
    data = dict(
        secret="test",
        alert_id="test-001",
        symbol="OANDA:XAUUSD",
        timeframe="5",
        timestamp=1,
        price=2400,
        ema20=2398,
        ema50=2395,
        rsi=60,
        atr=5,
        trend_1h="bullish",
        setup="long",
        daily_pnl=0,
        open_positions=0,
    )
    data.update(overrides)
    return TradingViewAlert(**data)


def test_bullish_alignment_can_buy():
    decision = rules_decision(base_alert())
    assert decision.action == "BUY"
    assert decision.stop_loss < decision.entry < decision.take_profit


def test_mixed_data_waits():
    decision = rules_decision(base_alert(
        price=2400,
        ema20=2402,
        ema50=2395,
        rsi=50,
        trend_1h="neutral",
        setup="long",
    ))
    assert decision.action == "WAIT"


def test_position_limit_waits():
    decision = rules_decision(base_alert(open_positions=2))
    assert decision.action == "WAIT"
    assert decision.source == "risk_gate"
