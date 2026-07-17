import math
import time
from datetime import datetime, timezone
from typing import Any

from .config import settings
from .market_analysis import analyze_market
from .news import fetch_context
from .session import trading_window_status


# Demo-testing release threshold. This is a technical-quality score,
# not a claimed probability that the trade will win.
MINIMUM_SIGNAL_CONFIDENCE = 80
SIGNAL_EXPIRY_MINUTES = 15


def _round_price(value: float) -> float:
    return round(float(value), 3)


def _floor_to_lot_step(
    value: float,
    step: float,
) -> float:
    if value <= 0 or step <= 0:
        return 0.0

    stepped = math.floor(
        (value + 1e-12) / step
    ) * step

    step_text = f"{step:.10f}".rstrip("0")
    decimal_places = (
        len(step_text.split(".")[1])
        if "." in step_text
        else 0
    )

    return round(
        stepped,
        decimal_places,
    )


def _calculate_lot_size(
    balance_gbp: float,
    risk_percent: float,
    entry: float,
    stop_loss: float,
) -> dict[str, Any]:
    stop_distance = abs(
        entry - stop_loss
    )

    if stop_distance <= 0:
        return {
            "lot": 0.0,
            "raw_lot": 0.0,
            "risk_gbp": 0.0,
            "estimated_loss_gbp": 0.0,
            "warning": "Invalid stop-loss distance",
        }

    if settings.xauusd_contract_size <= 0:
        return {
            "lot": 0.0,
            "raw_lot": 0.0,
            "risk_gbp": 0.0,
            "estimated_loss_gbp": 0.0,
            "warning": "Invalid contract size",
        }

    if settings.gbpusd_rate <= 0:
        return {
            "lot": 0.0,
            "raw_lot": 0.0,
            "risk_gbp": 0.0,
            "estimated_loss_gbp": 0.0,
            "warning": "Invalid GBPUSD conversion rate",
        }

    risk_gbp = (
        balance_gbp
        * risk_percent
        / 100.0
    )
    risk_usd = (
        risk_gbp
        * settings.gbpusd_rate
    )
    loss_per_lot_usd = (
        stop_distance
        * settings.xauusd_contract_size
    )
    raw_lot = (
        risk_usd
        / loss_per_lot_usd
    )

    warning = None

    if raw_lot < settings.xauusd_min_lot:
        lot = 0.0
        warning = (
            "Calculated size is below the "
            "configured minimum lot"
        )
    else:
        capped_lot = min(
            raw_lot,
            settings.xauusd_max_lot,
        )
        lot = _floor_to_lot_step(
            capped_lot,
            settings.xauusd_lot_step,
        )

        if lot < settings.xauusd_min_lot:
            lot = 0.0
            warning = (
                "Rounded size is below the "
                "configured minimum lot"
            )

    estimated_loss_gbp = (
        lot
        * loss_per_lot_usd
        / settings.gbpusd_rate
    )

    return {
        "lot": lot,
        "raw_lot": round(
            raw_lot,
            4,
        ),
        "risk_gbp": round(
            risk_gbp,
            2,
        ),
        "estimated_loss_gbp": round(
            estimated_loss_gbp,
            2,
        ),
        "warning": warning,
    }


def _wait_result(
    reason: str,
    confidence: int,
    analysis: dict[str, Any],
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "status": "ok",
        "action": "WAIT",
        "confidence": confidence,
        "reason": reason,
        "setup_type": None,
        "entry_zone": None,
        "entry": None,
        "stop_loss": None,
        "take_profits": [],
        "demo_lot": None,
        "live_lot": None,
        "risk_reward": None,
        "expires_at": None,
        "warnings": warnings or [],
        "analysis": analysis,
        "read_only": True,
    }


def _calendar_is_unavailable(
    warnings: list[str],
) -> bool:
    calendar_error_phrases = (
        "Economic calendar unavailable",
        "FMP_API_KEY not configured",
    )

    return any(
        phrase in warning
        for warning in warnings
        for phrase in calendar_error_phrases
    )


def _format_lot(
    sizing: dict[str, Any],
) -> str:
    lot = float(sizing["lot"])

    if lot <= 0:
        return "Below minimum lot"

    return f"{lot:.2f}"


def _build_telegram_message(
    result: dict[str, Any],
) -> str:
    action = result["action"]
    icon = "🟢" if action == "BUY" else "🔴"
    entry_zone = result["entry_zone"]
    take_profits = result["take_profits"]
    setup_type = str(
        result.get("setup_type")
        or "qualified_setup"
    ).replace("_", " ").title()

    lines = [
        f"{icon} {action} XAUUSD",
        "",
        "Chart: 5 Minute",
        f"Setup: {setup_type}",
        (
            "Entry zone: "
            f"{entry_zone['low']:.3f}"
            "–"
            f"{entry_zone['high']:.3f}"
        ),
        (
            "Suggested entry: "
            f"{result['entry']:.3f}"
        ),
        (
            "SL: "
            f"{result['stop_loss']:.3f}"
        ),
        (
            "TP1: "
            f"{take_profits[0]['price']:.3f}"
        ),
        (
            "TP2: "
            f"{take_profits[1]['price']:.3f}"
        ),
        (
            "TP3: "
            f"{take_profits[2]['price']:.3f}"
        ),
        "",
        (
            "Demo lot: "
            f"{_format_lot(result['demo_sizing'])}"
        ),
        (
            "Live lot: "
            f"{_format_lot(result['live_sizing'])}"
        ),
        "",
        (
            "Confidence: "
            f"{result['confidence']}%"
        ),
        (
            "Reason: "
            f"{result['reason']}"
        ),
        (
            "Valid for: "
            f"{SIGNAL_EXPIRY_MINUTES} minutes"
        ),
        "",
        (
            "Lot sizes are estimates until "
            "MT5 is connected."
        ),
        "Manual approval only — no order was placed.",
    ]

    return "\n".join(lines)


def build_live_signal() -> dict[str, Any]:
    """
    Build one complete read-only XAUUSD decision using:

    - live OANDA prices and completed candles
    - hierarchical multi-timeframe technical analysis
    - configured UK trading hours
    - official economic-calendar protection
    - optional headline context
    - an 80-point demo-testing release threshold
    - estimated demo and live lot sizes

    This function cannot place, edit or close trades.
    """

    current_timestamp = int(
        time.time()
    )

    allowed, session_reason = (
        trading_window_status(
            current_timestamp
        )
    )

    analysis = analyze_market()

    if not allowed:
        return _wait_result(
            reason=session_reason,
            confidence=98,
            analysis=analysis,
        )

    context = fetch_context(
        current_timestamp
    )

    if _calendar_is_unavailable(
        context.warnings
    ):
        return _wait_result(
            reason=(
                "Economic calendar unavailable; "
                "new trades are temporarily blocked"
            ),
            confidence=99,
            analysis=analysis,
            warnings=context.warnings,
        )

    if context.blocked:
        return _wait_result(
            reason=(
                context.block_reason
                or "High-impact US event"
            ),
            confidence=98,
            analysis=analysis,
            warnings=context.warnings,
        )

    technical_signal = analysis["signal"]
    action = str(
        technical_signal["action"]
    ).upper()
    confidence = int(
        technical_signal["confidence"]
    )

    if action not in {
        "BUY",
        "SELL",
    }:
        return _wait_result(
            reason=technical_signal["reason"],
            confidence=confidence,
            analysis=analysis,
            warnings=context.warnings,
        )

    if confidence < MINIMUM_SIGNAL_CONFIDENCE:
        return _wait_result(
            reason=(
                "Technical setup confidence is "
                f"below {MINIMUM_SIGNAL_CONFIDENCE}%"
            ),
            confidence=confidence,
            analysis=analysis,
            warnings=context.warnings,
        )

    entry_zone = technical_signal.get(
        "entry_zone"
    )
    take_profits = technical_signal.get(
        "take_profits"
    )
    stop_loss_value = technical_signal.get(
        "stop_loss"
    )

    if (
        not isinstance(entry_zone, dict)
        or not isinstance(take_profits, list)
        or len(take_profits) < 3
        or stop_loss_value is None
    ):
        return _wait_result(
            reason=(
                "The technical setup is missing a complete "
                "entry, stop-loss or take-profit plan"
            ),
            confidence=confidence,
            analysis=analysis,
            warnings=context.warnings,
        )

    entry = float(
        entry_zone["average"]
    )
    stop_loss = float(
        stop_loss_value
    )

    demo_sizing = _calculate_lot_size(
        balance_gbp=(
            settings.demo_balance_gbp
        ),
        risk_percent=(
            settings.demo_risk_percent
        ),
        entry=entry,
        stop_loss=stop_loss,
    )

    live_sizing = _calculate_lot_size(
        balance_gbp=(
            settings.live_balance_gbp
        ),
        risk_percent=(
            settings.live_risk_percent
        ),
        entry=entry,
        stop_loss=stop_loss,
    )

    expiry_timestamp = (
        current_timestamp
        + SIGNAL_EXPIRY_MINUTES * 60
    )
    expiry = datetime.fromtimestamp(
        expiry_timestamp,
        tz=timezone.utc,
    ).isoformat()

    result = {
        "status": "ok",
        "action": action,
        "confidence": confidence,
        "reason": technical_signal["reason"],
        "reasons": technical_signal.get(
            "reasons",
            [],
        ),
        "setup_type": technical_signal.get(
            "setup_type"
        ),
        "execution_timeframe": technical_signal[
            "execution_timeframe"
        ],
        "entry_zone": {
            "low": _round_price(
                entry_zone["low"]
            ),
            "high": _round_price(
                entry_zone["high"]
            ),
            "average": _round_price(entry),
        },
        "entry": _round_price(entry),
        "stop_loss": _round_price(
            stop_loss
        ),
        "take_profits": take_profits,
        "risk_reward": technical_signal[
            "risk_reward"
        ],
        "demo_lot": demo_sizing["lot"],
        "live_lot": live_sizing["lot"],
        "demo_sizing": demo_sizing,
        "live_sizing": live_sizing,
        "expires_at": expiry,
        "news_events": context.events,
        "news_headlines": context.headlines,
        "warnings": context.warnings,
        "market": analysis,
        "read_only": True,
    }

    result["telegram_message"] = (
        _build_telegram_message(result)
    )

    return result
