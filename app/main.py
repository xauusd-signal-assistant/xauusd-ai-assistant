import hmac
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query

from .ai import review
from .config import settings
from .db import alert_exists, init_db, list_signals, save_signal
from .models import SignalDecision, TradingViewAlert
from .news import fetch_context
from .notifications import send_telegram
from .oanda_client import check_oanda_connection
from .position_size import add_lots
from .risk import rules_decision, wait


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="XAUUSD AI Assistant",
    version="1.0.0",
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
        "economic_calendar": bool(settings.fmp_api_key),
        "news": bool(settings.newsapi_key),
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
    alert_age = abs(current_timestamp - alert.timestamp)

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
            baseline.source = "fallback"
            decision = baseline

    decision = add_lots(alert, decision)
    save_signal(alert, decision)

    try:
        send_telegram(decision)
    except Exception:
        pass

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
