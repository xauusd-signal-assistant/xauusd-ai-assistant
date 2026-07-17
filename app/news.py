from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone

import httpx

from .config import settings
from .official_calendar import fetch_official_calendar


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


def fetch_context(timestamp: int) -> NewsContext:
    now = datetime.fromtimestamp(
        timestamp,
        tz=timezone.utc,
    )

    headlines: list[dict] = []
    warnings: list[str] = []

    official_calendar = fetch_official_calendar(
        timestamp
    )

    events = official_calendar.events
    blocked = official_calendar.blocked
    reason = official_calendar.block_reason

    warnings.extend(
        official_calendar.warnings
    )

    official_sources_working = all(
        official_calendar.sources.values()
    )

    if not official_sources_working:
        warnings.append(
            "Economic calendar unavailable: "
            "one or more official calendar sources failed"
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

            articles = response.json().get(
                "articles",
                [],
            )

            for article in articles[:8]:
                source = article.get(
                    "source"
                ) or {}

                headlines.append(
                    {
                        "title": article.get(
                            "title"
                        ),
                        "source": source.get(
                            "name"
                        ),
                        "publishedAt": article.get(
                            "publishedAt"
                        ),
                        "description": article.get(
                            "description"
                        ),
                    }
                )

        except Exception as exc:
            warnings.append(
                "News feed unavailable: "
                f"{type(exc).__name__}"
            )

    else:
        warnings.append(
            "NEWSAPI_KEY not configured; "
            "headline context is incomplete"
        )

    return NewsContext(
        blocked=blocked,
        block_reason=reason,
        events=events[:30],
        headlines=headlines[:8],
        warnings=warnings,
    )
