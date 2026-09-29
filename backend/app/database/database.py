import sqlite3
from pathlib import Path

from app.config import settings

DB_PATH = Path(settings.DATABASE_URL.replace("sqlite:///", "")).resolve()


def get_connection() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    conn = get_connection()
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS team_rules (
                id TEXT PRIMARY KEY,
                text TEXT NOT NULL,
                category TEXT NOT NULL,
                source TEXT NOT NULL,
                created_at TEXT NOT NULL,
                usage_count INTEGER DEFAULT 0,
                active INTEGER DEFAULT 1
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS reviews (
                id TEXT PRIMARY KEY,
                filename TEXT,
                language TEXT,
                summary TEXT,
                score INTEGER,
                code TEXT,
                findings TEXT,
                memory_used TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS feedback (
                id TEXT PRIMARY KEY,
                review_id TEXT NOT NULL,
                finding_id TEXT NOT NULL,
                action TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.commit()
    finally:
        conn.close()
