from datetime import datetime, time
from zoneinfo import ZoneInfo
from .config import settings


def _clock(value: str) -> time:
    hour, minute = map(int, value.split(":"))
    return time(hour, minute)


def trading_window_status(timestamp: int) -> tuple[bool, str]:
    local = datetime.fromtimestamp(timestamp, ZoneInfo(settings.timezone))
    now = local.time()
    session_start = _clock(settings.session_start)
    session_end = _clock(settings.session_end)
    blackout_start = _clock(settings.hard_blackout_start)
    blackout_end = _clock(settings.hard_blackout_end)

    if blackout_start <= now < blackout_end:
        return False, (
            f"Hard volatility blackout {settings.hard_blackout_start}–"
            f"{settings.hard_blackout_end} UK time"
        )
    if not session_start <= now <= session_end:
        return False, (
            f"Outside configured trading session {settings.session_start}–"
            f"{settings.session_end} UK time"
        )
    return True, "Inside configured trading session"
