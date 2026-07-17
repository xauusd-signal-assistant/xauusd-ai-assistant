from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone

import httpx

from .config import settings


KEYWORDS = (
    "gold OR XAUUSD OR Federal Reserve OR Fed OR Powell OR FOMC OR "
    "US inflation OR CPI OR PPI OR PCE OR nonfarm payrolls OR NFP "
    "OR US dollar OR Treasury yields OR tariffs OR geopolitical"
)


@dataclass
class NewsContext:
    blocked: bool
    block_reason: str | None
    events: list[dict]
    headlines: list[dict]
    warnings: list[str]

    def as_dict(self) -> dict:
        return asdict(self)


def _parse_dt(value: str) -> datetime | None:
    if not value:
        return None

    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def fetch_context(timestamp: int) -> NewsContext:
    now = datetime.fromtimestamp(timestamp, tz=timezone.utc)

    events: list[dict] = []
    headlines: list[dict] = []
    warnings: list[str] = []

    blocked = False
    reason = None

    if settings.fmp_api_key:
        try:
            start = (now - timedelta(days=1)).date().isoformat()
            end = (now + timedelta(days=1)).date().isoformat()

            response = httpx.get(
                "https://financialmodelingprep.com/stable/economic-calendar",
                params={
                    "from": start,
                    "to": end,
                    "apikey": settings.fmp_api_key,
                },
                timeout=8,
            )
            response.raise_for_status()

            payload = response.json()

            if isinstance(payload, list):
                raw = payload
            elif isinstance(payload, dict):
                raw = payload.get(
                    "economicCalendar",
                    payload.get("data", []),
                )
            else:
                raw = []

            for item in raw:
                country = str(item.get("country", "")).upper()
                currency = str(item.get("currency", "")).upper()
                impact = str(item.get("impact", "")).lower()

                event_time = item.get("date") or item.get("time")
                event_dt = _parse_dt(str(event_time or ""))

                if (
                    country not in {"US", "USA", "UNITED STATES"}
                    and currency != "USD"
                ):
                    continue

                if impact not in {"high", "3"}:
                    continue

                event = {
                    "event": item.get("event"),
                    "time": event_time,
                    "impact": item.get("impact"),
                    "actual": item.get("actual"),
                    "estimate": item.get("estimate"),
                    "previous": item.get("previous"),
                }
                events.append(event)

                if event_dt:
                    if event_dt.tzinfo is None:
                        event_dt = event_dt.replace(tzinfo=timezone.utc)

                    delta_minutes = (
                        now - event_dt.astimezone(timezone.utc)
                    ).total_seconds() / 60

                    if (
                        -settings.event_blackout_minutes_before
                        <= delta_minutes
                        <= settings.event_blackout_minutes_after
                    ):
                        blocked = True
                        reason = (
                            "High-impact US event near signal time: "
                            f"{item.get('event')} ({event_time})"
                        )

        except Exception as exc:
            warnings.append(
                f"Economic calendar unavailable: {type(exc).__name__}"
            )
    else:
        warnings.append(
            "FMP_API_KEY not configured; "
            "economic-calendar protection is incomplete"
        )

    if settings.newsapi_key:
        try:
            published_after = now - timedelta(
                hours=settings.news_lookback_hours
            )

            response = httpx.get(
                "https://newsapi.org/v2/everything",
                params={
                    "q": KEYWORDS,
                    "from": published_after.isoformat(),
                    "to": now.isoformat(),
                    "language": "en",
                    "sortBy": "publishedAt",
                    "pageSize": 12,
                    "apiKey": settings.newsapi_key,
                },
                timeout=8,
            )
            response.raise_for_status()

            for article in response.json().get("articles", [])[:8]:
                headlines.append(
                    {
                        "title": article.get("title"),
                        "source": (
                            article.get("source") or {}
                        ).get("name"),
                        "publishedAt": article.get("publishedAt"),
                        "description": article.get("description"),
                    }
                )

        except Exception as exc:
            warnings.append(
                f"News feed unavailable: {type(exc).__name__}"
            )
    else:
        warnings.append(
            "NEWSAPI_KEY not configured; headline context is incomplete"
        )

    return NewsContext(
        blocked,
        reason,
        events[:10],
        headlines[:8],
        warnings,
    )
