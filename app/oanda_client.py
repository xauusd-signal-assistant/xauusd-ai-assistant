from typing import Any

import httpx

from .config import settings


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


def get_account_summary() -> dict[str, Any]:
    """
    Read the OANDA account summary.

    This function cannot place, edit, or close trades.
    """

    if not settings.oanda_account_id:
        raise RuntimeError("OANDA_ACCOUNT_ID is not configured")

    url = (
        f"{_base_url()}/v3/accounts/"
        f"{settings.oanda_account_id}/summary"
    )

    with httpx.Client(timeout=10.0) as client:
        response = client.get(
            url,
            headers=_headers(),
        )
        response.raise_for_status()
        payload = response.json()

    account = payload.get("account")

    if not isinstance(account, dict):
        raise RuntimeError("OANDA returned an invalid account response")

    return account


def check_oanda_connection() -> bool:
    """
    Return True only when the stored OANDA credentials work.
    """

    try:
        get_account_summary()
        return True
    except (httpx.HTTPError, RuntimeError, ValueError):
        return False
