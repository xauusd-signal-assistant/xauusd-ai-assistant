import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import settings
from .models import SignalDecision, TradingViewAlert


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def connect() -> sqlite3.Connection:
    database_path = Path(settings.database_path)

    database_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    connection = sqlite3.connect(
        database_path,
        timeout=15,
    )

    connection.row_factory = sqlite3.Row

    connection.execute(
        "PRAGMA busy_timeout = 15000"
    )

    connection.execute(
        "PRAGMA journal_mode = WAL"
    )

    return connection


def init_db() -> None:
    with connect() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                alert_id TEXT NOT NULL UNIQUE,
                received_at TEXT NOT NULL,
                symbol TEXT NOT NULL,
                timeframe TEXT NOT NULL,
                alert_json TEXT NOT NULL,
                decision_json TEXT NOT NULL
            )
            """
        )

        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS scanner_signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fingerprint TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL,
                action TEXT NOT NULL,
                confidence INTEGER NOT NULL,
                entry REAL,
                stop_loss REAL,
                expires_at TEXT,
                sent_to_telegram INTEGER NOT NULL DEFAULT 0,
                result_json TEXT NOT NULL
            )
            """
        )

        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS
            idx_scanner_signals_created_at
            ON scanner_signals(created_at)
            """
        )

        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS
            idx_scanner_signals_action
            ON scanner_signals(action)
            """
        )

        connection.commit()


def alert_exists(
    alert_id: str,
) -> bool:
    with connect() as connection:
        row = connection.execute(
            """
            SELECT 1
            FROM signals
            WHERE alert_id = ?
            """,
            (alert_id,),
        ).fetchone()

    return row is not None


def save_signal(
    alert: TradingViewAlert,
    decision: SignalDecision,
) -> None:
    with connect() as connection:
        connection.execute(
            """
            INSERT INTO signals (
                alert_id,
                received_at,
                symbol,
                timeframe,
                alert_json,
                decision_json
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                alert.alert_id,
                _utc_now(),
                alert.symbol,
                alert.timeframe,
                json.dumps(
                    alert.model_dump(
                        exclude={"secret"},
                    )
                ),
                json.dumps(
                    decision.model_dump()
                ),
            ),
        )

        connection.commit()


def list_signals(
    limit: int = 50,
) -> list[dict[str, Any]]:
    with connect() as connection:
        rows = connection.execute(
            """
            SELECT *
            FROM signals
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    return [
        {
            "id": row["id"],
            "alert_id": row["alert_id"],
            "received_at": row["received_at"],
            "symbol": row["symbol"],
            "timeframe": row["timeframe"],
            "alert": json.loads(
                row["alert_json"]
            ),
            "decision": json.loads(
                row["decision_json"]
            ),
        }
        for row in rows
    ]


def scanner_signal_exists(
    fingerprint: str,
) -> bool:
    """
    Check whether this exact scanner setup has already
    been recorded and processed.
    """

    with connect() as connection:
        row = connection.execute(
            """
            SELECT 1
            FROM scanner_signals
            WHERE fingerprint = ?
            """,
            (fingerprint,),
        ).fetchone()

    return row is not None


def save_scanner_signal(
    fingerprint: str,
    result: dict[str, Any],
    sent_to_telegram: bool,
) -> None:
    """
    Save one OANDA scanner decision.

    The unique fingerprint prevents the same setup from
    being sent repeatedly.
    """

    action = str(
        result.get("action", "WAIT")
    ).upper()

    confidence = int(
        result.get("confidence", 0) or 0
    )

    entry = result.get("entry")
    stop_loss = result.get("stop_loss")
    expires_at = result.get("expires_at")

    with connect() as connection:
        connection.execute(
            """
            INSERT OR IGNORE INTO scanner_signals (
                fingerprint,
                created_at,
                action,
                confidence,
                entry,
                stop_loss,
                expires_at,
                sent_to_telegram,
                result_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                fingerprint,
                _utc_now(),
                action,
                confidence,
                entry,
                stop_loss,
                expires_at,
                1 if sent_to_telegram else 0,
                json.dumps(result),
            ),
        )

        connection.commit()


def get_latest_scanner_signal() -> dict[str, Any] | None:
    with connect() as connection:
        row = connection.execute(
            """
            SELECT *
            FROM scanner_signals
            ORDER BY id DESC
            LIMIT 1
            """
        ).fetchone()

    if row is None:
        return None

    return {
        "id": row["id"],
        "fingerprint": row["fingerprint"],
        "created_at": row["created_at"],
        "action": row["action"],
        "confidence": row["confidence"],
        "entry": row["entry"],
        "stop_loss": row["stop_loss"],
        "expires_at": row["expires_at"],
        "sent_to_telegram": bool(
            row["sent_to_telegram"]
        ),
        "result": json.loads(
            row["result_json"]
        ),
    }


def list_scanner_signals(
    limit: int = 50,
) -> list[dict[str, Any]]:
    with connect() as connection:
        rows = connection.execute(
            """
            SELECT *
            FROM scanner_signals
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    return [
        {
            "id": row["id"],
            "fingerprint": row["fingerprint"],
            "created_at": row["created_at"],
            "action": row["action"],
            "confidence": row["confidence"],
            "entry": row["entry"],
            "stop_loss": row["stop_loss"],
            "expires_at": row["expires_at"],
            "sent_to_telegram": bool(
                row["sent_to_telegram"]
            ),
            "result": json.loads(
                row["result_json"]
            ),
        }
        for row in rows
    ]
