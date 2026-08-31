"""
Асинхронный слой подключения к SQLite.
Одно общее соединение на процесс (через aiosqlite), WAL-режим для
конкурентного чтения/записи, автосоздание схемы и индексов при старте.

ВАЖНО (Railway): DB_PATH должен указывать на директорию, примонтированную
как Volume (например /data/support.db) — иначе база будет теряться
при каждом редеплое, т.к. файловая система контейнера эфемерна.
"""
import logging
import os

import aiosqlite

from bot.config import DB_PATH

logger = logging.getLogger(__name__)

_connection: aiosqlite.Connection | None = None


async def get_connection() -> aiosqlite.Connection:
    global _connection
    if _connection is None:
        db_dir = os.path.dirname(DB_PATH)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)
        _connection = await aiosqlite.connect(DB_PATH)
        _connection.row_factory = aiosqlite.Row
        await _connection.execute("PRAGMA journal_mode=WAL")
        await _connection.execute("PRAGMA foreign_keys=ON")
        await _connection.execute("PRAGMA busy_timeout=5000")
        logger.info(f"SQLite подключена: {DB_PATH}")
    return _connection


async def close_connection():
    global _connection
    if _connection is not None:
        await _connection.close()
        _connection = None


SCHEMA_STATEMENTS = [
    """CREATE TABLE IF NOT EXISTS issues (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        message_id INTEGER,
        chat_id INTEGER,
        author_id INTEGER,
        author_name TEXT,
        username TEXT,
        text TEXT,
        type TEXT,
        status TEXT DEFAULT 'open',
        priority TEXT DEFAULT 'low',
        tags TEXT,
        responsible TEXT,
        created_at TIMESTAMP,
        reminder_sent INTEGER DEFAULT 0,
        closed_by INTEGER,
        closed_at TIMESTAMP,
        file_id TEXT,
        file_url TEXT,
        title TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS comments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        issue_id INTEGER,
        user_id INTEGER,
        user_name TEXT,
        text TEXT,
        created_at TIMESTAMP
    )""",
    """CREATE TABLE IF NOT EXISTS rating (
        user_id INTEGER PRIMARY KEY,
        points INTEGER DEFAULT 0,
        last_updated TIMESTAMP
    )""",
    """CREATE TABLE IF NOT EXISTS audit_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        issue_id INTEGER,
        user_id INTEGER,
        action TEXT,
        old_value TEXT,
        new_value TEXT,
        created_at TIMESTAMP
    )""",
    """CREATE TABLE IF NOT EXISTS votes (
        issue_id INTEGER,
        user_id INTEGER,
        vote INTEGER,
        PRIMARY KEY (issue_id, user_id)
    )""",
    """CREATE TABLE IF NOT EXISTS banned_users (
        user_id INTEGER PRIMARY KEY,
        reason TEXT,
        banned_at TIMESTAMP
    )""",
    """CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS responsible_users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE
    )""",
]

INDEX_STATEMENTS = [
    "CREATE INDEX IF NOT EXISTS idx_issues_status ON issues(status)",
    "CREATE INDEX IF NOT EXISTS idx_issues_created_at ON issues(created_at)",
    "CREATE INDEX IF NOT EXISTS idx_issues_author_id ON issues(author_id)",
    "CREATE INDEX IF NOT EXISTS idx_issues_username ON issues(username)",
    "CREATE INDEX IF NOT EXISTS idx_issues_responsible ON issues(responsible)",
    "CREATE INDEX IF NOT EXISTS idx_issues_message_id ON issues(message_id)",
    "CREATE INDEX IF NOT EXISTS idx_comments_issue_id ON comments(issue_id)",
    "CREATE INDEX IF NOT EXISTS idx_audit_log_issue_id ON audit_log(issue_id)",
]


async def init_db(default_responsible: list[str], auto_close_default_days: int):
    conn = await get_connection()
    for stmt in SCHEMA_STATEMENTS:
        await conn.execute(stmt)

    # Мягкая миграция: добавить недостающие колонки, если база создана старой версией бота
    cursor = await conn.execute("PRAGMA table_info(issues)")
    existing_cols = {row[1] for row in await cursor.fetchall()}
    for col in ["priority", "tags", "username", "responsible", "closed_by", "closed_at", "file_id", "file_url", "title"]:
        if col not in existing_cols:
            await conn.execute(f"ALTER TABLE issues ADD COLUMN {col} TEXT")

    for stmt in INDEX_STATEMENTS:
        await conn.execute(stmt)

    for username in default_responsible:
        await conn.execute(
            "INSERT OR IGNORE INTO responsible_users (username) VALUES (?)", (username,)
        )
    await conn.execute(
        "INSERT OR IGNORE INTO settings (key, value) VALUES ('auto_close_days', ?)",
        (str(auto_close_default_days),),
    )
    await conn.commit()
    logger.info("База данных инициализирована")
