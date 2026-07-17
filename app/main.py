import hmac
import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query

from .ai import review
from .auto_scanner import start_auto_scanner, stop_auto_scanner
from .config import settings
from .db import (
    alert_exists,
    init_db,
    list_scanner_signals,
    list_signals,
    save_signal,
)
from .live_signal import MINIMUM_SIGNAL_CONFIDENCE, build_live_signal
from .market_analysis import analyze_market
from .models import SignalDecision, TradingViewAlert
from .news import fetch_context
from .notifications import send_telegram
from .oanda_client import (
    check_oanda_connection,
    get_candles,
    get_current_price,
)
from .position_size import add_lots
from .risk import rules_decision, wait
from .scanner import SCANNER_COOLDOWN_MINUTES


LOGGER = logging.getLogger("uvicorn.error")


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    scanner_task = start_auto_scanner()

    try:
        yield
    finally:
        await stop_auto_scanner(scanner_task)


app = FastAPI(
    title="XAUUSD AI Assistant",
    version="1.6.0",
    lifespan=lifespan,
)


@app.get("/health")
def health():
    return {
        "status": "ok",
        "openai": bool(
            settings.enable_openai
            and settings.openai_api_key
        ),
        "telegram": bool(
            settings.telegram_bot_token
            and settings.telegram_chat_id
        ),
        "economic_calendar": True,
        "news": bool(settings.newsapi_key),
        "oanda_configured": bool(
            settings.oanda_api_token
            and settings.oanda_account_id
        ),
        "scanner_automatic": True,
        "scanner_interval_seconds": 60,
        "scanner_min_confidence": MINIMUM_SIGNAL_CONFIDENCE,
        "scanner_same_direction_cooldown_minutes": (
            SCANNER_COOLDOWN_MINUTES
        ),
        "signal_window_uk": (
            f"{settings.session_start}-"
            f"{settings.session_end}"
        ),
        "blackout_uk": (
            f"{settings.hard_blackout_start}-"
            f"{settings.hard_blackout_end}"
        ),
        "demo_balance_gbp": settings.demo_balance_gbp,
        "live_balance_gbp": settings.live_balance_gbp,
        "database_path": settings.database_path,
        "automatic_order_execution": False,
    }


@app.get("/health/oanda")
def health_oanda():
    configured = bool(
        settings.oanda_api_token
        and settings.oanda_account_id
    )

    return {
        "configured": configured,
        "connected": (
            check_oanda_connection()
            if configured
            else False
        ),
        "environment": settings.oanda_env,
        "instrument": settings.oanda_instrument,
        "read_only": True,
    }


@app.get("/health/oanda/market")
def health_oanda_market():
    """
    Test the live XAUUSD price and completed-candle feed.
    This endpoint is read-only.
    """

    try:
        price = get_current_price()
        timeframes = {
            "1m": "M1",
            "5m": "M5",
            "15m": "M15",
            "30m": "M30",
            "1h": "H1",
            "4h": "H4",
        }

        latest_candles = {}

        for label, granularity in timeframes.items():
            candles = get_candles(
                granularity=granularity,
                count=20,
            )
            latest_candles[label] = candles[-1]

        return {
            "status": "ok",
            "instrument": settings.oanda_instrument,
            "price": price,
            "latest_completed_candles": latest_candles,
            "read_only": True,
        }

    except Exception as exc:
        LOGGER.exception("OANDA market health check failed")
        return {
            "status": "error",
            "error_type": type(exc).__name__,
            "instrument": settings.oanda_instrument,
            "read_only": True,
        }


@app.get("/health/oanda/analysis")
def health_oanda_analysis():
    """
    Run the hierarchical multi-timeframe technical analysis.
    This endpoint is read-only.
    """

    try:
        return analyze_market()
    except Exception as exc:
        LOGGER.exception("OANDA technical analysis failed")
        return {
            "status": "error",
            "error_type": type(exc).__name__,
            "instrument": settings.oanda_instrument,
            "read_only": True,
        }


@app.get("/health/oanda/live-signal")
def health_oanda_live_signal():
    """
    Build one complete live signal without sending it.
    This endpoint is read-only.
    """

    try:
        return build_live_signal()
    except Exception as exc:
        LOGGER.exception("Live-signal preview failed")
        return {
            "status": "error",
            "error_type": type(exc).__name__,
            "instrument": settings.oanda_instrument,
            "read_only": True,
        }


@app.get("/health/oanda/scanner/run")
def run_scanner_preview():
    """
    Build a manual scanner preview without sending Telegram messages.

    The automatic background scanner remains responsible for sending
    qualified BUY/SELL alerts. Keeping this public route read-only
    prevents another person from triggering Telegram alerts.
    """

    try:
        result = build_live_signal()
        return {
            **result,
            "manual_preview": True,
            "sent_to_telegram": False,
            "read_only": True,
        }
    except Exception as exc:
        LOGGER.exception("Manual scanner preview failed")
        return {
            "status": "error",
            "error_type": type(exc).__name__,
            "instrument": settings.oanda_instrument,
            "sent_to_telegram": False,
            "read_only": True,
        }


@app.post(
    "/webhook/tradingview",
    response_model=SignalDecision,
)
def webhook(alert: TradingViewAlert):
    secret_matches = hmac.compare_digest(
        alert.secret,
        settings.webhook_secret,
    )

    if not secret_matches:
        raise HTTPException(
            status_code=401,
            detail="Unauthorized",
        )

    current_timestamp = int(time.time())
    alert_age = abs(
        current_timestamp - alert.timestamp
    )

    if alert_age > settings.max_alert_age_seconds:
        raise HTTPException(
            status_code=408,
            detail="Stale alert",
        )

    if alert_exists(alert.alert_id):
        raise HTTPException(
            status_code=409,
            detail="Duplicate alert",
        )

    baseline = rules_decision(alert)
    context = fetch_context(alert.timestamp)

    if context.blocked:
        decision = wait(
            context.block_reason
            or "High-impact US event",
            confidence=98,
        )
    else:
        try:
            decision = review(
                alert,
                baseline,
                context.as_dict(),
            )
        except Exception:
            LOGGER.exception(
                "OpenAI review failed; using deterministic fallback"
            )
            baseline.source = "fallback"
            decision = baseline

    # add_lots accepts the completed decision only.
    # Passing both alert and decision caused the previous 500 error.
    decision = add_lots(decision)

    save_signal(
        alert,
        decision,
    )

    try:
        send_telegram(decision)
    except Exception:
        LOGGER.exception(
            "TradingView Telegram notification failed"
        )

    return decision


@app.get("/signals")
def signals(
    limit: int = Query(
        default=50,
        ge=1,
        le=500,
    ),
):
    return list_signals(limit)


@app.get("/scanner-signals")
def scanner_signals(
    limit: int = Query(
        default=50,
        ge=1,
        le=500,
    ),
):
    return list_scanner_signals(limit)
