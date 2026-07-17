import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any

from .db import (
    get_latest_scanner_signal,
    save_scanner_signal,
    scanner_signal_exists,
)
from .live_signal import build_live_signal
from .notifications import send_live_signal


SCANNER_COOLDOWN_MINUTES = 60
MINIMUM_CONFIDENCE = 90


def _parse_datetime(
    value: str | None,
) -> datetime | None:
    if not value:
        return None

    try:
        parsed = datetime.fromisoformat(
            value.replace("Z", "+00:00")
        )

        if parsed.tzinfo is None:
            parsed = parsed.replace(
                tzinfo=timezone.utc
            )

        return parsed.astimezone(
            timezone.utc
        )

    except (TypeError, ValueError):
        return None


def _signal_fingerprint(
    result: dict[str, Any],
) -> str:
    """
    Create a stable identifier for one scanner setup.

    The completed 5-minute candle time is included so
    repeated scans of the same candle cannot send the
    same signal more than once.
    """

    market = result.get("market") or {}
    timeframes = market.get("timeframes") or {}
    five_minute = timeframes.get("5m") or {}

    take_profits = result.get(
        "take_profits",
        [],
    )

    tp1 = (
        take_profits[0].get("price")
        if (
            isinstance(take_profits, list)
            and take_profits
            and isinstance(
                take_profits[0],
                dict,
            )
        )
        else None
    )

    fingerprint_data = {
        "instrument": market.get(
            "instrument",
            "XAU_USD",
        ),
        "action": result.get("action"),
        "five_minute_candle": five_minute.get(
            "time"
        ),
        "entry": result.get("entry"),
        "stop_loss": result.get(
            "stop_loss"
        ),
        "tp1": tp1,
    }

    encoded = json.dumps(
        fingerprint_data,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")

    return hashlib.sha256(
        encoded
    ).hexdigest()


def _same_direction_cooldown_active(
    result: dict[str, Any],
) -> bool:
    """
    Prevent repeated signals in the same direction for
    one hour after a Telegram signal has been sent.
    """

    latest = get_latest_scanner_signal()

    if latest is None:
        return False

    if not latest.get(
        "sent_to_telegram",
        False,
    ):
        return False

    current_action = str(
        result.get("action", "")
    ).upper()

    latest_action = str(
        latest.get("action", "")
    ).upper()

    if current_action != latest_action:
        return False

    created_at = _parse_datetime(
        latest.get("created_at")
    )

    if created_at is None:
        return False

    cooldown_end = created_at + timedelta(
        minutes=SCANNER_COOLDOWN_MINUTES
    )

    return datetime.now(
        timezone.utc
    ) < cooldown_end


def _price_is_inside_entry_zone(
    result: dict[str, Any],
) -> bool:
    """
    Refuse to send a signal when the current market price
    has already moved outside its calculated entry zone.
    """

    entry_zone = result.get(
        "entry_zone"
    )

    market = result.get("market") or {}
    price = market.get("price") or {}

    if not isinstance(
        entry_zone,
        dict,
    ):
        return False

    try:
        current_mid = float(
            price["mid"]
        )

        entry_low = float(
            entry_zone["low"]
        )

        entry_high = float(
            entry_zone["high"]
        )

    except (
        KeyError,
        TypeError,
        ValueError,
    ):
        return False

    return (
        entry_low
        <= current_mid
        <= entry_high
    )


def run_scanner_once() -> dict[str, Any]:
    """
    Run one complete XAUUSD scanning cycle.

    This function:

    - reads live OANDA prices and candles
    - checks the official economic calendar
    - evaluates the multi-timeframe setup
    - blocks low-confidence or stale entries
    - prevents duplicate Telegram signals
    - records released signals persistently

    It cannot place, edit or close trades.
    """

    result = build_live_signal()

    action = str(
        result.get("action", "WAIT")
    ).upper()

    confidence = int(
        result.get("confidence", 0)
        or 0
    )

    if action == "WAIT":
        return {
            "status": "completed",
            "action": "WAIT",
            "confidence": confidence,
            "reason": result.get(
                "reason",
                "No valid setup",
            ),
            "sent_to_telegram": False,
            "recorded": False,
            "read_only": True,
        }

    if action not in {
        "BUY",
        "SELL",
    }:
        return {
            "status": "skipped",
            "action": action,
            "reason": "Unsupported scanner action",
            "sent_to_telegram": False,
            "recorded": False,
            "read_only": True,
        }

    if confidence < MINIMUM_CONFIDENCE:
        return {
            "status": "skipped",
            "action": action,
            "confidence": confidence,
            "reason": (
                "Confidence is below "
                f"{MINIMUM_CONFIDENCE}%"
            ),
            "sent_to_telegram": False,
            "recorded": False,
            "read_only": True,
        }

    if not _price_is_inside_entry_zone(
        result
    ):
        return {
            "status": "skipped",
            "action": action,
            "confidence": confidence,
            "reason": (
                "Current price has moved outside "
                "the entry zone"
            ),
            "sent_to_telegram": False,
            "recorded": False,
            "read_only": True,
        }

    fingerprint = _signal_fingerprint(
        result
    )

    if scanner_signal_exists(
        fingerprint
    ):
        return {
            "status": "duplicate",
            "action": action,
            "confidence": confidence,
            "reason": (
                "This exact scanner setup has "
                "already been processed"
            ),
            "fingerprint": fingerprint,
            "sent_to_telegram": False,
            "recorded": False,
            "read_only": True,
        }

    if _same_direction_cooldown_active(
        result
    ):
        return {
            "status": "cooldown",
            "action": action,
            "confidence": confidence,
            "reason": (
                "A recent signal in the same "
                "direction is still inside the "
                f"{SCANNER_COOLDOWN_MINUTES}-minute "
                "cooldown"
            ),
            "fingerprint": fingerprint,
            "sent_to_telegram": False,
            "recorded": False,
            "read_only": True,
        }

    sent = False

    try:
        sent = send_live_signal(
            result,
            include_wait=False,
        )

    finally:
        save_scanner_signal(
            fingerprint=fingerprint,
            result=result,
            sent_to_telegram=sent,
        )

    return {
        "status": (
            "sent"
            if sent
            else "recorded_not_sent"
        ),
        "action": action,
        "confidence": confidence,
        "reason": result.get("reason"),
        "entry": result.get("entry"),
        "stop_loss": result.get(
            "stop_loss"
        ),
        "take_profits": result.get(
            "take_profits",
            [],
        ),
        "demo_lot": result.get(
            "demo_lot"
        ),
        "live_lot": result.get(
            "live_lot"
        ),
        "fingerprint": fingerprint,
        "sent_to_telegram": sent,
        "recorded": True,
        "read_only": True,
    }
