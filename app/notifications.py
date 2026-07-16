import html, httpx
from .config import settings

def send_telegram(decision):
    if not settings.telegram_bot_token or not settings.telegram_chat_id: return False
    if decision.action == "WAIT" and not settings.notify_wait_signals: return False
    if decision.action != "WAIT" and decision.confidence < 90: return False
    if decision.action == "WAIT":
        text = f"🟡 <b>WAIT</b>\n\n{html.escape(decision.reason)}\nNo trade."
    else:
        icon = "🟢" if decision.action == "BUY" else "🔴"
        demo = f"{decision.demo_lot:.2f}" if decision.demo_lot is not None else "Below minimum"
        live = f"{decision.live_lot:.2f}" if decision.live_lot is not None else "Below minimum"
        text = (f"{icon} <b>{decision.action} XAUUSD</b>\n\n"
                f"Chart: <b>{decision.execution_timeframe}</b>\n"
                f"Entry: <b>{decision.entry}</b>\nSL: <b>{decision.stop_loss}</b>\nTP: <b>{decision.take_profit}</b>\n\n"
                f"Demo lot: <b>{demo}</b>\nLive lot: <b>{live}</b>\n\n"
                f"Confidence: <b>{decision.confidence}%</b>\nReason: {html.escape(decision.reason)}\n\n"
                f"<i>Review manually before placing in MT5.</i>")
    response = httpx.post(f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage",
        json={"chat_id": settings.telegram_chat_id, "text": text, "parse_mode": "HTML"}, timeout=8)
    response.raise_for_status(); return True
