import sqlite3
import json
import time
from typing import Optional, List, Dict, Any
from config import config


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(config.DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    conn = get_conn()
    cur = conn.cursor()

    cur.executescript("""
        CREATE TABLE IF NOT EXISTS settings (
            key   TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS groups (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id         TEXT    NOT NULL UNIQUE,
            title           TEXT    NOT NULL DEFAULT '',
            added_at        REAL    NOT NULL DEFAULT 0,
            last_sent_at    REAL    NOT NULL DEFAULT 0,
            cycle_interval  INTEGER,
            active          INTEGER NOT NULL DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS message_store (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            media_type  TEXT,
            file_id     TEXT,
            caption     TEXT,
            text        TEXT,
            created_at  REAL NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS flood_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id     TEXT NOT NULL,
            wait_secs   INTEGER NOT NULL,
            occurred_at REAL NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS send_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id     TEXT NOT NULL,
            sent_at     REAL NOT NULL DEFAULT 0,
            status      TEXT NOT NULL DEFAULT 'ok'
        );
    """)

    # default settings
    defaults = {
        "cycle_interval_minutes": "17",
        "per_message_delay_seconds": "60",
        "running": "0",
        "total_sent": "0",
    }
    for k, v in defaults.items():
        cur.execute(
            "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (k, v)
        )

    conn.commit()
    conn.close()


# ── settings ────────────────────────────────────────────────────────────────

def get_setting(key: str) -> Optional[str]:
    conn = get_conn()
    row = conn.execute(
        "SELECT value FROM settings WHERE key = ?", (key,)
    ).fetchone()
    conn.close()
    return row["value"] if row else None


def set_setting(key: str, value: str) -> None:
    conn = get_conn()
    conn.execute(
        "INSERT INTO settings (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, str(value)),
    )
    conn.commit()
    conn.close()


def increment_total_sent(n: int = 1) -> None:
    conn = get_conn()
    conn.execute(
        "UPDATE settings SET value = CAST(CAST(value AS INTEGER) + ? AS TEXT) "
        "WHERE key = 'total_sent'",
        (n,),
    )
    conn.commit()
    conn.close()


# ── groups ──────────────────────────────────────────────────────────────────

def add_group(chat_id: str, title: str = "") -> bool:
    """Returns True if newly inserted, False if already existed."""
    conn = get_conn()
    try:
        conn.execute(
            "INSERT INTO groups (chat_id, title, added_at, active) VALUES (?, ?, ?, 1)",
            (str(chat_id), title, time.time()),
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()


def remove_group(chat_id: str) -> bool:
    conn = get_conn()
    cur = conn.execute("DELETE FROM groups WHERE chat_id = ?", (str(chat_id),))
    conn.commit()
    conn.close()
    return cur.rowcount > 0


def get_all_groups() -> List[Dict[str, Any]]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM groups WHERE active = 1 ORDER BY id ASC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_group(chat_id: str) -> Optional[Dict[str, Any]]:
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM groups WHERE chat_id = ?", (str(chat_id),)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def update_group_last_sent(chat_id: str, ts: float) -> None:
    conn = get_conn()
    conn.execute(
        "UPDATE groups SET last_sent_at = ? WHERE chat_id = ?",
        (ts, str(chat_id)),
    )
    conn.commit()
    conn.close()


def set_group_cycle_interval(chat_id: str, minutes: Optional[int]) -> None:
    conn = get_conn()
    conn.execute(
        "UPDATE groups SET cycle_interval = ? WHERE chat_id = ?",
        (minutes, str(chat_id)),
    )
    conn.commit()
    conn.close()


def update_group_title(chat_id: str, title: str) -> None:
    conn = get_conn()
    conn.execute(
        "UPDATE groups SET title = ? WHERE chat_id = ?",
        (title, str(chat_id)),
    )
    conn.commit()
    conn.close()


# ── message store ────────────────────────────────────────────────────────────

def save_message(
    text: Optional[str] = None,
    media_type: Optional[str] = None,
    file_id: Optional[str] = None,
    caption: Optional[str] = None,
) -> int:
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO message_store (text, media_type, file_id, caption, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (text, media_type, file_id, caption, time.time()),
    )
    row_id = cur.lastrowid
    conn.commit()
    conn.close()
    return row_id


def get_latest_message() -> Optional[Dict[str, Any]]:
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM message_store ORDER BY id DESC LIMIT 1"
    ).fetchone()
    conn.close()
    return dict(row) if row else None


# ── flood log ────────────────────────────────────────────────────────────────

def log_flood(chat_id: str, wait_secs: int) -> None:
    conn = get_conn()
    conn.execute(
        "INSERT INTO flood_log (chat_id, wait_secs, occurred_at) VALUES (?, ?, ?)",
        (str(chat_id), wait_secs, time.time()),
    )
    conn.commit()
    conn.close()


def get_recent_flood_logs(limit: int = 10) -> List[Dict[str, Any]]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM flood_log ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── send log ─────────────────────────────────────────────────────────────────

def log_send(chat_id: str, status: str = "ok") -> None:
    conn = get_conn()
    conn.execute(
        "INSERT INTO send_log (chat_id, sent_at, status) VALUES (?, ?, ?)",
        (str(chat_id), time.time(), status),
    )
    conn.commit()
    conn.close()
