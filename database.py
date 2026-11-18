import sqlite3
import time
import json
from config import config


def get_conn():
    conn = sqlite3.connect(config.DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_conn()
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS groups (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        chat_id TEXT UNIQUE NOT NULL,
        title TEXT DEFAULT '',
        added_at REAL DEFAULT 0,
        last_sent_at REAL DEFAULT 0,
        cycle_interval INTEGER,
        active INTEGER DEFAULT 1
    );

    CREATE TABLE IF NOT EXISTS message_store (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        media_type TEXT,
        file_id TEXT,
        caption TEXT,
        text TEXT,
        created_at REAL DEFAULT 0
    );

    CREATE TABLE IF NOT EXISTS flood_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        chat_id TEXT NOT NULL,
        wait_secs INTEGER NOT NULL,
        occurred_at REAL DEFAULT 0
    );

    CREATE TABLE IF NOT EXISTS send_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        chat_id TEXT NOT NULL,
        sent_at REAL DEFAULT 0,
        status TEXT DEFAULT 'ok'
    );
    """)

    # New columns — existing database compatibility
    columns = {
        "file_path": "TEXT",
        "entities_json": "TEXT"
    }

    existing = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(message_store)")
    }

    for name, data_type in columns.items():
        if name not in existing:
            conn.execute(
                f"ALTER TABLE message_store ADD COLUMN {name} {data_type}"
            )

    defaults = {
        "cycle_interval_minutes": "17",
        "per_message_delay_seconds": "60",
        "running": "0",
        "total_sent": "0",
        "last_any_send_at": "0"
    }

    for key, value in defaults.items():
        conn.execute(
            "INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)",
            (key, value)
        )

    conn.commit()
    conn.close()


def get_setting(key, default=None):
    conn = get_conn()
    row = conn.execute(
        "SELECT value FROM settings WHERE key=?", (key,)
    ).fetchone()
    conn.close()
    return row["value"] if row else default


def set_setting(key, value):
    conn = get_conn()
    conn.execute("""
        INSERT INTO settings(key,value) VALUES(?,?)
        ON CONFLICT(key) DO UPDATE SET value=excluded.value
    """, (key, str(value)))
    conn.commit()
    conn.close()


def increment_total_sent(amount=1):
    current = int(get_setting("total_sent", "0"))
    set_setting("total_sent", current + amount)


def add_group(chat_id, title=""):
    conn = get_conn()
    try:
        conn.execute("""
            INSERT INTO groups(chat_id,title,added_at,active)
            VALUES(?,?,?,1)
        """, (str(chat_id), title, time.time()))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()


def remove_group(chat_id):
    conn = get_conn()
    cur = conn.execute(
        "DELETE FROM groups WHERE chat_id=?", (str(chat_id),)
    )
    conn.commit()
    conn.close()
    return cur.rowcount > 0


def get_all_groups():
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM groups WHERE active=1 ORDER BY id"
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_group(chat_id):
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM groups WHERE chat_id=?", (str(chat_id),)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def update_group_last_sent(chat_id, timestamp=None):
    timestamp = timestamp or time.time()
    conn = get_conn()
    conn.execute(
        "UPDATE groups SET last_sent_at=? WHERE chat_id=?",
        (timestamp, str(chat_id))
    )
    conn.commit()
    conn.close()


def set_group_cycle_interval(chat_id, minutes):
    conn = get_conn()
    conn.execute(
        "UPDATE groups SET cycle_interval=? WHERE chat_id=?",
        (minutes, str(chat_id))
    )
    conn.commit()
    conn.close()


def update_group_title(chat_id, title):
    conn = get_conn()
    conn.execute(
        "UPDATE groups SET title=? WHERE chat_id=?",
        (title, str(chat_id))
    )
    conn.commit()
    conn.close()


def save_message(
    text="",
    media_type="text",
    file_path=None,
    entities=None,
    caption=None
):
    conn = get_conn()
    cur = conn.execute("""
        INSERT INTO message_store
        (text,media_type,file_path,entities_json,caption,created_at)
        VALUES(?,?,?,?,?,?)
    """, (
        text or "",
        media_type,
        file_path,
        json.dumps(entities or []),
        caption,
        time.time()
    ))
    message_id = cur.lastrowid
    conn.commit()
    conn.close()
    return message_id


def get_latest_message():
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM message_store ORDER BY id DESC LIMIT 1"
    ).fetchone()
    conn.close()

    if not row:
        return None

    result = dict(row)
    try:
        result["entities"] = json.loads(
            result.get("entities_json") or "[]"
        )
    except Exception:
        result["entities"] = []

    return result


def log_flood(chat_id, wait_secs):
    conn = get_conn()
    conn.execute("""
        INSERT INTO flood_log(chat_id,wait_secs,occurred_at)
        VALUES(?,?,?)
    """, (str(chat_id), int(wait_secs), time.time()))
    conn.commit()
    conn.close()


def get_recent_flood_logs(limit=10):
    conn = get_conn()
    rows = conn.execute("""
        SELECT * FROM flood_log ORDER BY id DESC LIMIT ?
    """, (limit,)).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def log_send(chat_id, status="ok"):
    conn = get_conn()
    conn.execute("""
        INSERT INTO send_log(chat_id,sent_at,status)
        VALUES(?,?,?)
    """, (str(chat_id), time.time(), status))
    conn.commit()
    conn.close()


def get_send_stats():
    conn = get_conn()

    total = conn.execute(
        "SELECT COUNT(*) AS n FROM send_log"
    ).fetchone()["n"]

    success = conn.execute(
        "SELECT COUNT(*) AS n FROM send_log WHERE status='ok'"
    ).fetchone()["n"]

    failed = total - success

    conn.close()

    return {
        "total": total,
        "success": success,
        "failed": failed
        }
