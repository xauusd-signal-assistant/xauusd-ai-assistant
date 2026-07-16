import json
import sqlite3
from datetime import datetime, timezone
from .config import settings
from .models import TradingViewAlert, SignalDecision


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(settings.database_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with connect() as conn:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            alert_id TEXT NOT NULL UNIQUE,
            received_at TEXT NOT NULL,
            symbol TEXT NOT NULL,
            timeframe TEXT NOT NULL,
            alert_json TEXT NOT NULL,
            decision_json TEXT NOT NULL
        )
        """)


def alert_exists(alert_id: str) -> bool:
    with connect() as conn:
        row = conn.execute(
            "SELECT 1 FROM signals WHERE alert_id = ?",
            (alert_id,),
        ).fetchone()
    return row is not None


def save_signal(alert: TradingViewAlert, decision: SignalDecision) -> None:
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO signals
            (alert_id, received_at, symbol, timeframe, alert_json, decision_json)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                alert.alert_id,
                datetime.now(timezone.utc).isoformat(),
                alert.symbol,
                alert.timeframe,
                json.dumps(alert.model_dump(exclude={"secret"})),
                json.dumps(decision.model_dump()),
            ),
        )


def list_signals(limit: int = 50) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM signals ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()

    return [
        {
            "id": row["id"],
            "alert_id": row["alert_id"],
            "received_at": row["received_at"],
            "symbol": row["symbol"],
            "timeframe": row["timeframe"],
            "alert": json.loads(row["alert_json"]),
            "decision": json.loads(row["decision_json"]),
        }
        for row in rows
    ]
