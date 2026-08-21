import json
import os
import sqlite3
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), "rag.db")


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    with get_conn() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL DEFAULT '新对话',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id INTEGER NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                filename TEXT NOT NULL UNIQUE,
                file_path TEXT NOT NULL,
                size INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            );
            """
        )
        _migrate_legacy_tables(conn)


def _migrate_legacy_tables(conn: sqlite3.Connection):
    tables = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    if "chat_sessions" not in tables:
        return

    old_sessions = conn.execute(
        "SELECT id, title, created_at, updated_at FROM chat_sessions"
    ).fetchall()
    for s in old_sessions:
        conn.execute(
            """
            INSERT OR IGNORE INTO conversations (id, title, created_at, updated_at)
            VALUES (?, ?, ?, ?)
            """,
            (s["id"], s["title"], s["created_at"], s["updated_at"]),
        )

    if "chat_messages" in tables:
        old_messages = conn.execute(
            "SELECT session_id, role, content, created_at FROM chat_messages"
        ).fetchall()
        for m in old_messages:
            conn.execute(
                """
                INSERT INTO messages (conversation_id, role, content, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (m["session_id"], m["role"], m["content"], m["created_at"]),
            )

    conn.execute("DROP TABLE IF EXISTS chat_messages")
    conn.execute("DROP TABLE IF EXISTS chat_sessions")


def list_conversations():
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT id, title, created_at, updated_at
            FROM conversations
            ORDER BY updated_at DESC
            """
        ).fetchall()
        return [dict(row) for row in rows]


def create_conversation(title: str = "新对话") -> int:
    now = _now()
    with get_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO conversations (title, created_at, updated_at)
            VALUES (?, ?, ?)
            """,
            (title, now, now),
        )
        return cur.lastrowid


def ensure_default_conversation() -> int:
    conversations = list_conversations()
    if conversations:
        return conversations[0]["id"]
    return create_conversation("新对话")


def touch_conversation(conversation_id: int):
    with get_conn() as conn:
        conn.execute(
            "UPDATE conversations SET updated_at = ? WHERE id = ?",
            (_now(), conversation_id),
        )


def update_conversation_title(conversation_id: int, title: str):
    title = (title or "新对话").strip()[:40] or "新对话"
    with get_conn() as conn:
        conn.execute(
            "UPDATE conversations SET title = ?, updated_at = ? WHERE id = ?",
            (title, _now(), conversation_id),
        )


def delete_conversation(conversation_id: int) -> bool:
    with get_conn() as conn:
        cur = conn.execute(
            "DELETE FROM conversations WHERE id = ?", (conversation_id,)
        )
        return cur.rowcount > 0


def get_conversation_messages(conversation_id: int):
    with get_conn() as conn:
        conv = conn.execute(
            "SELECT id, title FROM conversations WHERE id = ?", (conversation_id,)
        ).fetchone()
        if not conv:
            return None

        rows = conn.execute(
            """
            SELECT id, role, content, created_at
            FROM messages
            WHERE conversation_id = ?
            ORDER BY id ASC
            """,
            (conversation_id,),
        ).fetchall()

        return {
            "conversation": dict(conv),
            "messages": [dict(row) for row in rows],
        }


def count_messages(conversation_id: int) -> int:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS cnt FROM messages WHERE conversation_id = ?",
            (conversation_id,),
        ).fetchone()
        return row["cnt"] if row else 0


def add_message(conversation_id: int, role: str, content: str) -> int:
    now = _now()
    with get_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO messages (conversation_id, role, content, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (conversation_id, role, content, now),
        )
        conn.execute(
            "UPDATE conversations SET updated_at = ? WHERE id = ?",
            (now, conversation_id),
        )
        return cur.lastrowid


def upsert_document(filename: str, file_path: str, size: int):
    now = _now()
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO documents (filename, file_path, size, created_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(filename) DO UPDATE SET
                file_path = excluded.file_path,
                size = excluded.size
            """,
            (filename, file_path, size, now),
        )


init_db()

# 兼容旧代码中的命名
list_sessions = list_conversations
create_session = create_conversation
get_session_messages = get_conversation_messages
delete_session = delete_conversation
touch_session = touch_conversation
update_session_title = update_conversation_title
