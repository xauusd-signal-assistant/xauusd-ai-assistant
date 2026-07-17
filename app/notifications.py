import html
from typing import Any

import httpx

from .config import settings


def _telegram_is_configured() -> bool:
    return bool(
        settings.telegram_bot_token
        and settings.telegram_chat_id
    )


def _send_message(text: str) -> bool:
    if not _telegram_is_configured():
        return False

    response = httpx.post(
        (
            "https://api.telegram.org/bot"
            f"{settings.telegram_bot_token}/sendMessage"
        ),
        json={
            "chat_id": settings.telegram_chat_id,
            "text": text,
            "parse_mode": "HTML",
        },
        timeout=8,
    )

    response.raise_for_status()
    return True


def send_telegram(decision) -> bool:
    """
    Send an existing TradingView decision to Telegram.
    """

    if not _telegram_is_configured():
        return False

    if (
        decision.action == "WAIT"
        and not settings.notify_wait_signals
    ):
        return False

    if (
        decision.action != "WAIT"
        and decision.confidence < 90
    ):
        return False

    if decision.action == "WAIT":
        text = (
            "🟡 <b>WAIT</b>\n\n"
            f"{html.escape(decision.reason)}\n"
            "No trade."
        )

    else:
        icon = (
            "🟢"
            if decision.action == "BUY"
            else "🔴"
        )

        demo = (
            f"{decision.demo_lot:.2f}"
            if decision.demo_lot is not None
            else "Below minimum"
        )

        live = (
            f"{decision.live_lot:.2f}"
            if decision.live_lot is not None
            else "Below minimum"
        )

        text = (
            f"{icon} <b>{decision.action} XAUUSD</b>\n\n"
            f"Chart: <b>{decision.execution_timeframe}</b>\n"
            f"Entry: <b>{decision.entry}</b>\n"
            f"SL: <b>{decision.stop_loss}</b>\n"
            f"TP: <b>{decision.take_profit}</b>\n\n"
            f"Demo lot: <b>{demo}</b>\n"
            f"Live lot: <b>{live}</b>\n\n"
            f"Confidence: <b>{decision.confidence}%</b>\n"
            f"Reason: {html.escape(decision.reason)}\n\n"
            "<i>Review manually before placing in MT5.</i>"
        )

    return _send_message(text)


def _format_live_lot(value: Any) -> str:
    try:
        lot = float(value)
    except (TypeError, ValueError):
        return "Unavailable"

    if lot <= 0:
        return "Below minimum"

    return f"{lot:.2f}"


def send_live_signal(
    result: dict[str, Any],
    include_wait: bool = False,
) -> bool:
    """
    Send a continuous OANDA scanner result to Telegram.

    WAIT messages are disabled by default so the automatic
    scanner does not send a message every minute.

    This function cannot place, edit or close trades.
    """

    if not _telegram_is_configured():
        return False

    action = str(
        result.get("action", "WAIT")
    ).upper()

    confidence = int(
        result.get("confidence", 0) or 0
    )

    reason = html.escape(
        str(
            result.get(
                "reason",
                "No reason supplied",
            )
        )
    )

    if action == "WAIT":
        if not include_wait:
            return False

        text = (
            "🟡 <b>WAIT</b>\n\n"
            f"{reason}\n"
            "No trade."
        )

        return _send_message(text)

    if action not in {"BUY", "SELL"}:
        return False

    if confidence < 90:
        return False

    entry_zone = result.get("entry_zone")

    if not isinstance(entry_zone, dict):
        return False

    take_profits = result.get(
        "take_profits",
        [],
    )

    if (
        not isinstance(take_profits, list)
        or len(take_profits) < 3
    ):
        return False

    entry = float(result["entry"])
    stop_loss = float(result["stop_loss"])

    entry_low = float(entry_zone["low"])
    entry_high = float(entry_zone["high"])

    tp1 = float(take_profits[0]["price"])
    tp2 = float(take_profits[1]["price"])
    tp3 = float(take_profits[2]["price"])

    demo_lot = _format_live_lot(
        result.get("demo_lot")
    )

    live_lot = _format_live_lot(
        result.get("live_lot")
    )

    icon = (
        "🟢"
        if action == "BUY"
        else "🔴"
    )

    text = (
        f"{icon} <b>{action} XAUUSD</b>\n\n"
        "Chart: <b>5 Minute</b>\n"
        f"Entry zone: <b>{entry_low:.3f}"
        f"–{entry_high:.3f}</b>\n"
        f"Suggested entry: <b>{entry:.3f}</b>\n"
        f"SL: <b>{stop_loss:.3f}</b>\n"
        f"TP1: <b>{tp1:.3f}</b>\n"
        f"TP2: <b>{tp2:.3f}</b>\n"
        f"TP3: <b>{tp3:.3f}</b>\n\n"
        f"Demo lot: <b>{demo_lot}</b>\n"
        f"Live lot: <b>{live_lot}</b>\n\n"
        f"Confidence: <b>{confidence}%</b>\n"
        f"Reason: {reason}\n"
        "Valid for: <b>15 minutes</b>\n\n"
        "<i>Manual MT5 execution only. "
        "Do not chase the entry if price has moved away.</i>"
    )

    return _send_message(text)
