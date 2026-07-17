from typing import Any

import httpx

from .config import settings


VALID_GRANULARITIES = {
    "M1",
    "M5",
    "M15",
    "M30",
    "H1",
    "H4",
}


def _base_url() -> str:
    environment = settings.oanda_env.strip().lower()

    if environment == "live":
        return "https://api-fxtrade.oanda.com"

    return "https://api-fxpractice.oanda.com"


def _headers() -> dict[str, str]:
    if not settings.oanda_api_token:
        raise RuntimeError("OANDA_API_TOKEN is not configured")

    return {
        "Authorization": f"Bearer {settings.oanda_api_token}",
        "Content-Type": "application/json",
    }


def _account_id() -> str:
    if not settings.oanda_account_id:
        raise RuntimeError("OANDA_ACCOUNT_ID is not configured")

    return settings.oanda_account_id


def _request_json(
    path: str,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    url = f"{_base_url()}{path}"

    with httpx.Client(timeout=15.0) as client:
        response = client.get(
            url,
            headers=_headers(),
            params=params,
        )
        response.raise_for_status()
        payload = response.json()

    if not isinstance(payload, dict):
        raise RuntimeError("OANDA returned an invalid response")

    return payload


def get_account_summary() -> dict[str, Any]:
    """
    Read the OANDA account summary.

    This function cannot place, edit, or close trades.
    """

    payload = _request_json(
        f"/v3/accounts/{_account_id()}/summary"
    )

    account = payload.get("account")

    if not isinstance(account, dict):
        raise RuntimeError(
            "OANDA returned an invalid account response"
        )

    return account


def get_current_price(
    instrument: str | None = None,
) -> dict[str, Any]:
    """
    Read the latest bid and ask price for XAUUSD.
    """

    selected_instrument = (
        instrument or settings.oanda_instrument
    ).strip().upper()

    payload = _request_json(
        f"/v3/accounts/{_account_id()}/pricing",
        params={
            "instruments": selected_instrument,
            "includeUnitsAvailable": "false",
        },
    )

    prices = payload.get("prices")

    if not isinstance(prices, list) or not prices:
        raise RuntimeError("OANDA returned no price data")

    price = prices[0]

    if not isinstance(price, dict):
        raise RuntimeError("OANDA returned invalid price data")

    bids = price.get("bids") or []
    asks = price.get("asks") or []

    bid = (
        float(bids[0]["price"])
        if bids
        else float(price["closeoutBid"])
    )

    ask = (
        float(asks[0]["price"])
        if asks
        else float(price["closeoutAsk"])
    )

    return {
        "instrument": selected_instrument,
        "time": price.get("time"),
        "status": price.get("status"),
        "bid": bid,
        "ask": ask,
        "mid": round((bid + ask) / 2, 5),
        "spread": round(ask - bid, 5),
    }


def get_candles(
    granularity: str,
    count: int = 250,
    instrument: str | None = None,
) -> list[dict[str, Any]]:
    """
    Read completed midpoint candles from OANDA.

    Supported granularities:
    M1, M5, M15, M30, H1 and H4.
    """

    selected_granularity = granularity.strip().upper()

    if selected_granularity not in VALID_GRANULARITIES:
        raise ValueError(
            f"Unsupported granularity: {selected_granularity}"
        )

    if count < 20 or count > 5000:
        raise ValueError(
            "Candle count must be between 20 and 5000"
        )

    selected_instrument = (
        instrument or settings.oanda_instrument
    ).strip().upper()

    payload = _request_json(
        (
            f"/v3/accounts/{_account_id()}/instruments/"
            f"{selected_instrument}/candles"
        ),
        params={
            "price": "M",
            "granularity": selected_granularity,
            "count": count,
            "smooth": "false",
        },
    )

    raw_candles = payload.get("candles")

    if not isinstance(raw_candles, list):
        raise RuntimeError("OANDA returned no candle data")

    candles: list[dict[str, Any]] = []

    for candle in raw_candles:
        if not isinstance(candle, dict):
            continue

        if not candle.get("complete", False):
            continue

        midpoint = candle.get("mid")

        if not isinstance(midpoint, dict):
            continue

        candles.append(
            {
                "time": candle.get("time"),
                "open": float(midpoint["o"]),
                "high": float(midpoint["h"]),
                "low": float(midpoint["l"]),
                "close": float(midpoint["c"]),
                "volume": int(candle.get("volume", 0)),
                "complete": True,
            }
        )

    if not candles:
        raise RuntimeError(
            "OANDA returned no completed candles"
        )

    return candles


def get_market_snapshot() -> dict[str, Any]:
    """
    Read current price and the latest candles for every
    timeframe used by the XAUUSD assistant.
    """

    return {
        "price": get_current_price(),
        "candles": {
            "1m": get_candles("M1"),
            "5m": get_candles("M5"),
            "15m": get_candles("M15"),
            "30m": get_candles("M30"),
            "1h": get_candles("H1"),
            "4h": get_candles("H4"),
        },
    }


def check_oanda_connection() -> bool:
    """
    Return True only when the stored OANDA credentials work.
    """

    try:
        get_account_summary()
        return True
    except (
        httpx.HTTPError,
        RuntimeError,
        ValueError,
        KeyError,
        TypeError,
    ):
        return False
