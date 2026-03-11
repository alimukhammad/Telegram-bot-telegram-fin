"""SQLite persistence layer.

Schema
------
watchlist   – per-user tracked pairs.
alerts      – per-user alert rules.
price_history – sampled prices used for rolling-window change alerts.
"""
from __future__ import annotations

import sqlite3
import time
from contextlib import contextmanager
from typing import Generator, List, Optional, Tuple

import config

# ---------------------------------------------------------------------------
# Connection helper
# ---------------------------------------------------------------------------

def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(config.DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def _db() -> Generator[sqlite3.Connection, None, None]:
    conn = _connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Schema initialisation
# ---------------------------------------------------------------------------

CREATE_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS watchlist (
        id        INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id   INTEGER NOT NULL,
        pair      TEXT    NOT NULL,
        UNIQUE(user_id, pair)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS alerts (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id         INTEGER NOT NULL,
        pair            TEXT    NOT NULL,
        alert_type      TEXT    NOT NULL,  -- 'price' | 'change'
        operator        TEXT    NOT NULL,  -- '>' | '<' | '>=' | '<='
        value           REAL    NOT NULL,
        window          TEXT,              -- NULL for price alerts; '5m'/'15m'/'1h' for change
        cooldown        INTEGER NOT NULL DEFAULT 300,
        last_triggered  REAL    NOT NULL DEFAULT 0,
        created_at      REAL    NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS price_history (
        id        INTEGER PRIMARY KEY AUTOINCREMENT,
        pair      TEXT NOT NULL,
        price     REAL NOT NULL,
        ts        REAL NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_ph_pair_ts ON price_history(pair, ts)",
    "CREATE INDEX IF NOT EXISTS idx_alerts_user ON alerts(user_id)",
    "CREATE INDEX IF NOT EXISTS idx_wl_user ON watchlist(user_id)",
]


def init_db() -> None:
    with _db() as conn:
        for stmt in CREATE_STATEMENTS:
            conn.execute(stmt)


# ---------------------------------------------------------------------------
# Watchlist
# ---------------------------------------------------------------------------

def add_pair(user_id: int, pair: str) -> bool:
    """Add *pair* to *user_id*'s watchlist.  Returns False if already present."""
    try:
        with _db() as conn:
            conn.execute(
                "INSERT INTO watchlist(user_id, pair) VALUES (?, ?)",
                (user_id, pair),
            )
        return True
    except sqlite3.IntegrityError:
        return False


def remove_pair(user_id: int, pair: str) -> bool:
    """Remove *pair* from *user_id*'s watchlist.  Returns False if not found."""
    with _db() as conn:
        cur = conn.execute(
            "DELETE FROM watchlist WHERE user_id=? AND pair=?",
            (user_id, pair),
        )
        return cur.rowcount > 0


def get_pairs(user_id: int) -> List[str]:
    with _db() as conn:
        rows = conn.execute(
            "SELECT pair FROM watchlist WHERE user_id=? ORDER BY pair",
            (user_id,),
        ).fetchall()
    return [r["pair"] for r in rows]


def get_all_watched_pairs() -> List[str]:
    """Return deduplicated list of all pairs across all users."""
    with _db() as conn:
        rows = conn.execute(
            "SELECT DISTINCT pair FROM watchlist"
        ).fetchall()
    return [r["pair"] for r in rows]


# ---------------------------------------------------------------------------
# Alerts
# ---------------------------------------------------------------------------

def add_alert(
    user_id: int,
    pair: str,
    alert_type: str,
    operator: str,
    value: float,
    window: Optional[str],
    cooldown: int,
) -> int:
    """Insert an alert row and return its id."""
    with _db() as conn:
        cur = conn.execute(
            """
            INSERT INTO alerts
                (user_id, pair, alert_type, operator, value, window, cooldown, last_triggered, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?)
            """,
            (user_id, pair, alert_type, operator, value, window, cooldown, time.time()),
        )
        return cur.lastrowid  # type: ignore[return-value]


def remove_alert(user_id: int, alert_id: int) -> bool:
    with _db() as conn:
        cur = conn.execute(
            "DELETE FROM alerts WHERE id=? AND user_id=?",
            (alert_id, user_id),
        )
        return cur.rowcount > 0


def get_alerts(user_id: int) -> List[sqlite3.Row]:
    with _db() as conn:
        return conn.execute(
            "SELECT * FROM alerts WHERE user_id=? ORDER BY id",
            (user_id,),
        ).fetchall()


def get_all_alerts() -> List[sqlite3.Row]:
    with _db() as conn:
        return conn.execute("SELECT * FROM alerts").fetchall()


def update_last_triggered(alert_id: int) -> None:
    with _db() as conn:
        conn.execute(
            "UPDATE alerts SET last_triggered=? WHERE id=?",
            (time.time(), alert_id),
        )


# ---------------------------------------------------------------------------
# Price history
# ---------------------------------------------------------------------------

def record_price(pair: str, price: float) -> None:
    with _db() as conn:
        conn.execute(
            "INSERT INTO price_history(pair, price, ts) VALUES (?, ?, ?)",
            (pair, price, time.time()),
        )


def get_price_at(pair: str, ts: float) -> Optional[float]:
    """Return the price sample closest to (but not after) *ts*."""
    with _db() as conn:
        row = conn.execute(
            """
            SELECT price FROM price_history
            WHERE pair=? AND ts<=?
            ORDER BY ts DESC LIMIT 1
            """,
            (pair, ts),
        ).fetchone()
    return row["price"] if row else None


def prune_price_history(max_age_seconds: int = 7200) -> None:
    """Delete price_history rows older than *max_age_seconds*."""
    cutoff = time.time() - max_age_seconds
    with _db() as conn:
        conn.execute("DELETE FROM price_history WHERE ts<?", (cutoff,))
