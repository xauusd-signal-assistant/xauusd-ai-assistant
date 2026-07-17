import asyncio
import logging
import time
from contextlib import suppress
from typing import Any

from .scanner import run_scanner_once


LOGGER = logging.getLogger(__name__)

SCAN_INTERVAL_SECONDS = 60
STARTUP_DELAY_SECONDS = 10


async def _run_one_cycle() -> dict[str, Any]:
    """
    Run the blocking scanner safely outside FastAPI's
    asynchronous event loop.
    """

    return await asyncio.to_thread(
        run_scanner_once
    )


async def auto_scanner_loop() -> None:
    """
    Continuously scan XAUUSD approximately once per minute.

    The underlying scanner already:

    - suppresses WAIT Telegram messages
    - requires at least 90% confidence
    - checks the official economic calendar
    - rejects price outside the entry zone
    - prevents duplicate signals
    - applies the same-direction cooldown
    - records released signals on the persistent disk

    This loop cannot place, modify or close trades.
    """

    LOGGER.info(
        "Automatic XAUUSD scanner starting in %s seconds",
        STARTUP_DELAY_SECONDS,
    )

    await asyncio.sleep(
        STARTUP_DELAY_SECONDS
    )

    while True:
        cycle_started = time.monotonic()

        try:
            result = await _run_one_cycle()

            LOGGER.info(
                (
                    "Scanner cycle completed: "
                    "status=%s action=%s confidence=%s "
                    "telegram=%s reason=%s"
                ),
                result.get("status"),
                result.get("action"),
                result.get("confidence"),
                result.get("sent_to_telegram"),
                result.get("reason"),
            )

        except asyncio.CancelledError:
            LOGGER.info(
                "Automatic XAUUSD scanner stopped"
            )
            raise

        except Exception:
            LOGGER.exception(
                "Automatic XAUUSD scanner cycle failed"
            )

        elapsed = (
            time.monotonic()
            - cycle_started
        )

        sleep_seconds = max(
            1.0,
            SCAN_INTERVAL_SECONDS - elapsed,
        )

        await asyncio.sleep(
            sleep_seconds
        )


def start_auto_scanner() -> asyncio.Task[None]:
    """
    Start one scanner background task.
    """

    return asyncio.create_task(
        auto_scanner_loop(),
        name="xauusd-auto-scanner",
    )


async def stop_auto_scanner(
    task: asyncio.Task[None] | None,
) -> None:
    """
    Stop the scanner cleanly during a Render restart
    or deployment.
    """

    if task is None or task.done():
        return

    task.cancel()

    with suppress(
        asyncio.CancelledError
    ):
        await task
