import html
import logging
from typing import Any

import httpx

from .config import settings
from .live_signal import MINIMUM_SIGNAL_CONFIDENCE


LOGGER = logging.getLogger("uvicorn.error")
TELEGRAM_TIMEOUT_SECONDS = 10


def _telegram_is_configured() -> bool:
    return bool(
        settings.telegram_bot_token
        and settings.telegram_chat_id
    )


def _send_message(text: str) -> bool:
    """
    Send one Telegram message without exposing secrets in logs.
    """

    if not _telegram_is_configured():
        LOGGER.error(
            "Telegram send blocked: bot token or chat ID is missing"
        )
        return False

    try:
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
            timeout=TELEGRAM_TIMEOUT_SECONDS,
        )
        response.raise_for_status()

    except httpx.HTTPStatusError as exc:
        LOGGER.error(
            "Telegram send failed with HTTP status %s",
            exc.response.status_code,
        )
        return False

    except httpx.RequestError as exc:
        LOGGER.error(
            "Telegram request failed: %s",
            type(exc).__name__,
        )
        return False

    LOGGER.info("Telegram message sent successfully")
    return True


def _format_lot(value: Any) -> str:
    try:
        lot = float(value)
    except (TypeError, ValueError):
        return "Unavailable"

    if lot <= 0:
        return "Below minimum"

    return f"{lot:.2f}"


def send_telegram(decision: Any) -> bool:
    """
    Send an existing TradingView decision to Telegram.

    BUY and SELL decisions use the same demo-testing confidence
    threshold as the continuous OANDA scanner.
    """

    if not _telegram_is_configured():
        LOGGER.error(
            "TradingView Telegram send blocked: Telegram is not configured"
        )
        return False

    action = str(
        getattr(decision, "action", "WAIT")
    ).upper()
    confidence = int(
        getattr(decision, "confidence", 0)
        or 0
    )
    reason = html.escape(
        str(
            getattr(
                decision,
                "reason",
                "No reason supplied",
            )
        )
    )

    if action == "WAIT":
        if not settings.notify_wait_signals:
            return False

        return _send_message(
            "⏸ WAIT\n\n"
            f"{reason}\n"
            "No trade."
        )

    if action not in {"BUY", "SELL"}:
        LOGGER.warning(
            "TradingView Telegram send rejected: unsupported action=%s",
            action,
        )
        return False

    if confidence < MINIMUM_SIGNAL_CONFIDENCE:
        LOGGER.info(
            (
                "TradingView Telegram send rejected: "
                "confidence=%s threshold=%s"
            ),
            confidence,
            MINIMUM_SIGNAL_CONFIDENCE,
        )
        return False

    icon = "🟢" if action == "BUY" else "🔴"

    text = (
        f"{icon} {action} XAUUSD\n\n"
        f"Chart: {html.escape(str(getattr(decision, 'execution_timeframe', 'Unknown')))}\n"
        f"Entry: {html.escape(str(getattr(decision, 'entry', 'Unavailable')))}\n"
        f"SL: {html.escape(str(getattr(decision, 'stop_loss', 'Unavailable')))}\n"
        f"TP: {html.escape(str(getattr(decision, 'take_profit', 'Unavailable')))}\n\n"
        f"Demo lot: {_format_lot(getattr(decision, 'demo_lot', None))}\n"
        f"Live lot: {_format_lot(getattr(decision, 'live_lot', None))}\n\n"
        f"Confidence: {confidence}%\n"
        f"Reason: {reason}\n\n"
        "Review manually before placing in MT5."
    )

    return _send_message(text)


def send_live_signal(
    result: dict[str, Any],
    include_wait: bool = False,
) -> bool:
    """
    Send a continuous OANDA scanner signal to Telegram.

    WAIT messages remain disabled by default. BUY and SELL signals
    are released at the same threshold used by live_signal.py.
    This function cannot place, edit or close trades.
    """

    if not _telegram_is_configured():
        LOGGER.error(
            "Scanner Telegram send blocked: Telegram is not configured"
        )
        return False

    action = str(
        result.get("action", "WAIT")
    ).upper()
    confidence = int(
        result.get("confidence", 0)
        or 0
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

        return _send_message(
            "⏸ WAIT\n\n"
            f"{reason}\n"
            "No trade."
        )

    if action not in {"BUY", "SELL"}:
        LOGGER.warning(
            "Scanner Telegram send rejected: unsupported action=%s",
            action,
        )
        return False

    if confidence < MINIMUM_SIGNAL_CONFIDENCE:
        LOGGER.info(
            (
                "Scanner Telegram send rejected: "
                "confidence=%s threshold=%s"
            ),
            confidence,
            MINIMUM_SIGNAL_CONFIDENCE,
        )
        return False

    entry_zone = result.get("entry_zone")
    take_profits = result.get(
        "take_profits",
        [],
    )

    if not isinstance(entry_zone, dict):
        LOGGER.error(
            "Scanner Telegram send rejected: entry zone is missing"
        )
        return False

    if (
        not isinstance(take_profits, list)
        or len(take_profits) < 3
    ):
        LOGGER.error(
            "Scanner Telegram send rejected: three take-profit levels are required"
        )
        return False

    try:
        entry = float(result["entry"])
        stop_loss = float(result["stop_loss"])
        entry_low = float(entry_zone["low"])
        entry_high = float(entry_zone["high"])
        tp1 = float(take_profits[0]["price"])
        tp2 = float(take_profits[1]["price"])
        tp3 = float(take_profits[2]["price"])

    except (KeyError, TypeError, ValueError):
        LOGGER.error(
            "Scanner Telegram send rejected: invalid trade-plan values"
        )
        return False

    setup_type = html.escape(
        str(
            result.get("setup_type")
            or "qualified_setup"
        )
        .replace("_", " ")
        .title()
    )
    demo_lot = _format_lot(
        result.get("demo_lot")
    )
    live_lot = _format_lot(
        result.get("live_lot")
    )
    icon = "🟢" if action == "BUY" else "🔴"

    text = (
        f"{icon} {action} XAUUSD\n\n"
        "Chart: 5 Minute\n"
        f"Setup: {setup_type}\n"
        f"Entry zone: {entry_low:.3f}–{entry_high:.3f}\n"
        f"Suggested entry: {entry:.3f}\n"
        f"SL: {stop_loss:.3f}\n"
        f"TP1: {tp1:.3f}\n"
        f"TP2: {tp2:.3f}\n"
        f"TP3: {tp3:.3f}\n\n"
        f"Demo lot: {demo_lot}\n"
        f"Live lot: {live_lot}\n\n"
        f"Confidence: {confidence}%\n"
        f"Reason: {reason}\n"
        "Valid for: 15 minutes\n\n"
        "Manual MT5 execution only. "
        "Do not chase the entry if price has moved away."
    )

    return _send_message(text)
