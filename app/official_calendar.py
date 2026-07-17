from __future__ import annotations

import calendar
import re
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from html import unescape
from typing import Any, Callable
from zoneinfo import ZoneInfo

import httpx

from .config import settings


EASTERN = ZoneInfo("America/New_York")
UTC = timezone.utc
CACHE_SECONDS = 6 * 60 * 60

NYFED_URL = (
    "https://www.newyorkfed.org/research/calendars/"
    "i-{month}{year}.html"
)
FED_URL = (
    "https://www.federalreserve.gov/newsevents/"
    "{year}-{month}.htm"
)

NYFED_HIGH_IMPACT = (
    "consumer price index",
    "producer price index",
    "employment situation",
    "nonfarm payroll",
    "personal income and the pce deflator",
    "personal income and outlays",
    "gross domestic product",
    "advance retail sales",
    "retail sales",
    "initial claims",
    "jolts",
    "ism manufacturing",
    "ism non-manufacturing",
)

FED_HIGH_IMPACT = (
    "fomc meeting",
    "fomc press conference",
    "fomc minutes",
    "monetary policy report",
    "economic outlook",
    "monetary policy",
    "inflation",
    "interest rate",
    "rate decision",
    "chair ",
    "chairman ",
    "powell",
)

_cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}


@dataclass
class OfficialCalendarContext:
    blocked: bool
    block_reason: str | None
    events: list[dict[str, Any]]
    warnings: list[str]
    sources: dict[str, bool]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _clean_lines(html: str) -> list[str]:
    html = re.sub(
        r"<(script|style|noscript)\b[^>]*>.*?</\1>",
        " ",
        html,
        flags=re.IGNORECASE | re.DOTALL,
    )
    text = re.sub(r"<[^>]+>", "\n", html)

    return [
        " ".join(unescape(line).split())
        for line in text.splitlines()
        if " ".join(unescape(line).split())
    ]


def _between(
    lines: list[str],
    start: str,
    endings: tuple[str, ...],
) -> list[str]:
    start_index = next(
        (
            index + 1
            for index, line in enumerate(lines)
            if line.casefold() == start.casefold()
        ),
        None,
    )

    if start_index is None:
        return []

    end_index = len(lines)

    for index in range(start_index, len(lines)):
        lowered = lines[index].casefold()

        if any(
            lowered.startswith(ending.casefold())
            for ending in endings
        ):
            end_index = index
            break

    return lines[start_index:end_index]


def _months(
    start: datetime,
    end: datetime,
) -> list[tuple[int, int]]:
    result: list[tuple[int, int]] = []
    year, month = start.year, start.month

    while (year, month) <= (end.year, end.month):
        result.append((year, month))

        if month == 12:
            year, month = year + 1, 1
        else:
            month += 1

    return result


def _download(url: str) -> str:
    with httpx.Client(
        timeout=15.0,
        follow_redirects=True,
        headers={
            "User-Agent": (
                "XAUUSD-AI-Assistant/1.0 "
                "official-calendar-reader"
            )
        },
    ) as client:
        response = client.get(url)
        response.raise_for_status()
        return response.text


def _cached(
    key: str,
    loader: Callable[[], list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    now = time.time()
    saved = _cache.get(key)

    if saved and now - saved[0] < CACHE_SECONDS:
        return saved[1]

    events = loader()
    _cache[key] = (now, events)
    return events


def _is_day(value: str) -> bool:
    return bool(re.fullmatch(r"0?[1-9]|[12][0-9]|3[01]", value))


def _nyfed_time(value: str) -> tuple[int, int] | None:
    match = re.fullmatch(
        r"\(?([01]?\d|2[0-3]):([0-5]\d)\)?",
        value,
    )
    return (
        (int(match.group(1)), int(match.group(2)))
        if match
        else None
    )


def _fed_time(value: str) -> tuple[int, int] | None:
    value = value.lower().replace(".", "")
    match = re.fullmatch(
        r"([1-9]|1[0-2]):([0-5]\d)\s*(am|pm)",
        value,
    )

    if not match:
        return None

    hour = int(match.group(1))
    minute = int(match.group(2))

    if match.group(3) == "pm" and hour != 12:
        hour += 12
    elif match.group(3) == "am" and hour == 12:
        hour = 0

    return hour, minute


def _utc_time(
    year: int,
    month: int,
    day: int,
    hour: int,
    minute: int,
) -> str:
    local = datetime(
        year,
        month,
        day,
        hour,
        minute,
        tzinfo=EASTERN,
    )
    return local.astimezone(UTC).isoformat()


def _event(
    title: str,
    event_time: str,
    source: str,
    source_url: str,
    category: str,
    details: str = "",
) -> dict[str, Any]:
    return {
        "event": title,
        "time": event_time,
        "impact": "high",
        "country": "US",
        "currency": "USD",
        "source": source,
        "source_url": source_url,
        "category": category,
        "details": details or None,
    }


def _parse_nyfed(
    html: str,
    year: int,
    month: int,
    url: str,
) -> list[dict[str, Any]]:
    label = f"{calendar.month_name[month]} {year}"
    body = _between(
        _clean_lines(html),
        label,
        ("Key:", "Top of page"),
    )

    if not body:
        raise RuntimeError("New York Fed calendar format changed")

    day: int | None = None
    pending: str | None = None
    events: list[dict[str, Any]] = []

    for line in body:
        if _is_day(line):
            day = int(line)
            pending = None
            continue

        parsed_time = _nyfed_time(line)

        if parsed_time and day and pending:
            if any(
                keyword in pending.casefold()
                for keyword in NYFED_HIGH_IMPACT
            ):
                hour, minute = parsed_time
                events.append(
                    _event(
                        pending,
                        _utc_time(
                            year,
                            month,
                            day,
                            hour,
                            minute,
                        ),
                        "Federal Reserve Bank of New York",
                        url,
                        "economic_release",
                    )
                )

            pending = None
            continue

        if day is not None:
            pending = line

    return events


def _parse_fed_section(
    body: list[str],
    year: int,
    month: int,
    url: str,
    category: str,
) -> list[dict[str, Any]]:
    current_time: tuple[int, int] | None = None
    text: list[str] = []
    events: list[dict[str, Any]] = []

    for line in body:
        if line.casefold() in {
            "time:",
            "release date(s):",
            "watch live",
        }:
            continue

        parsed_time = _fed_time(line)

        if parsed_time:
            current_time = parsed_time
            text = []
            continue

        if _is_day(line) and current_time and text:
            details = " | ".join(text)
            combined = details.casefold()

            if any(
                keyword in combined
                for keyword in FED_HIGH_IMPACT
            ):
                hour, minute = current_time
                title = next(
                    (
                        item
                        for item in text
                        if not item.casefold().startswith("at ")
                    ),
                    text[0],
                )
                events.append(
                    _event(
                        title,
                        _utc_time(
                            year,
                            month,
                            int(line),
                            hour,
                            minute,
                        ),
                        "Board of Governors of the Federal Reserve",
                        url,
                        category,
                        details,
                    )
                )

            current_time = None
            text = []
            continue

        if current_time:
            text.append(line)

    return events


def _parse_fed(
    html: str,
    year: int,
    month: int,
    url: str,
) -> list[dict[str, Any]]:
    label = f"{calendar.month_name[month]} {year}"
    lines = _between(
        _clean_lines(html),
        label,
        ("Last Update:", "Back to Top"),
    )

    if not lines:
        raise RuntimeError("Federal Reserve calendar format changed")

    specifications = (
        (
            "Speeches",
            (
                "Testimony",
                "FOMC Meetings",
                "Beige Book",
                "Statistical Releases",
                "Other",
            ),
            "speech",
        ),
        (
            "Testimony",
            (
                "FOMC Meetings",
                "Beige Book",
                "Statistical Releases",
                "Other",
            ),
            "testimony",
        ),
        (
            "FOMC Meetings",
            (
                "Beige Book",
                "Statistical Releases",
                "Other",
            ),
            "fomc",
        ),
    )

    events: list[dict[str, Any]] = []

    for section, endings, category in specifications:
        body = _between(lines, section, endings)
        events.extend(
            _parse_fed_section(
                body,
                year,
                month,
                url,
                category,
            )
        )

    return events


def _nyfed_url(year: int, month: int) -> str:
    return NYFED_URL.format(
        month=calendar.month_abbr[month].lower(),
        year=str(year)[-2:],
    )


def _fed_url(year: int, month: int) -> str:
    return FED_URL.format(
        year=year,
        month=calendar.month_name[month].lower(),
    )


def _event_datetime(event: dict[str, Any]) -> datetime:
    return datetime.fromisoformat(str(event["time"]))


def fetch_official_calendar(
    timestamp: int,
) -> OfficialCalendarContext:
    now = datetime.fromtimestamp(timestamp, tz=UTC)
    start = now - timedelta(days=2)
    end = now + timedelta(days=35)

    events: list[dict[str, Any]] = []
    warnings: list[str] = []
    sources = {
        "new_york_fed": False,
        "federal_reserve_board": False,
    }

    for year, month in _months(start, end):
        nyfed_url = _nyfed_url(year, month)

        try:
            events.extend(
                _cached(
                    f"nyfed:{year}:{month}",
                    lambda u=nyfed_url, y=year, m=month: (
                        _parse_nyfed(_download(u), y, m, u)
                    ),
                )
            )
            sources["new_york_fed"] = True
        except (httpx.HTTPError, RuntimeError, ValueError) as exc:
            warnings.append(
                "New York Fed calendar unavailable: "
                f"{type(exc).__name__}"
            )

        fed_url = _fed_url(year, month)

        try:
            events.extend(
                _cached(
                    f"fed:{year}:{month}",
                    lambda u=fed_url, y=year, m=month: (
                        _parse_fed(_download(u), y, m, u)
                    ),
                )
            )
            sources["federal_reserve_board"] = True
        except (httpx.HTTPError, RuntimeError, ValueError) as exc:
            warnings.append(
                "Federal Reserve calendar unavailable: "
                f"{type(exc).__name__}"
            )

    unique: dict[tuple[str, str], dict[str, Any]] = {}

    for event in events:
        key = (
            str(event["event"]).casefold(),
            str(event["time"]),
        )
        unique[key] = event

    events = sorted(
        (
            event
            for event in unique.values()
            if start <= _event_datetime(event) <= end
        ),
        key=_event_datetime,
    )

    blocked = False
    reason: str | None = None

    for event in events:
        minutes_from_event = (
            now - _event_datetime(event)
        ).total_seconds() / 60.0

        if (
            -settings.event_blackout_minutes_before
            <= minutes_from_event
            <= settings.event_blackout_minutes_after
        ):
            blocked = True
            reason = (
                "High-impact US event near signal time: "
                f"{event['event']} ({event['time']})"
            )
            break

    return OfficialCalendarContext(
        blocked=blocked,
        block_reason=reason,
        events=events,
        warnings=warnings,
        sources=sources,
    )
