"""
Репозиторий: все запросы к БД, асинхронные (aiosqlite), с общим
соединением из bot.db.connection.get_connection().

Отличия от исходной версии:
 - все функции async, не блокируют event loop бота
 - одно общее соединение вместо open/close на каждый вызов
 - исправлен баг в add_vote (обращение к закрытому соединению)
 - параметризованные запросы везде (защита от SQL-инъекций — было и раньше)
"""
from datetime import datetime, timedelta
from collections import Counter

from bot.db.connection import get_connection


# ---------- Settings ----------
async def get_setting(key: str, default=None):
    conn = await get_connection()
    cur = await conn.execute("SELECT value FROM settings WHERE key=?", (key,))
    row = await cur.fetchone()
    return row[0] if row else default


async def set_setting(key: str, value: str):
    conn = await get_connection()
    await conn.execute(
        "INSERT INTO settings (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )
    await conn.commit()


# ---------- Banned users ----------
async def is_banned(user_id: int) -> bool:
    conn = await get_connection()
    cur = await conn.execute("SELECT 1 FROM banned_users WHERE user_id=?", (user_id,))
    return await cur.fetchone() is not None


async def ban_user(user_id: int, reason: str = ""):
    conn = await get_connection()
    await conn.execute(
        "INSERT OR REPLACE INTO banned_users (user_id, reason, banned_at) VALUES (?, ?, ?)",
        (user_id, reason, datetime.now()),
    )
    await conn.commit()


async def unban_user(user_id: int):
    conn = await get_connection()
    await conn.execute("DELETE FROM banned_users WHERE user_id=?", (user_id,))
    await conn.commit()


# ---------- Audit log ----------
async def add_audit_log(issue_id, user_id, action, old_val="", new_val=""):
    conn = await get_connection()
    await conn.execute(
        "INSERT INTO audit_log (issue_id, user_id, action, old_value, new_value, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (issue_id, user_id, action, old_val, new_val, datetime.now()),
    )
    await conn.commit()


# ---------- Votes / rating ----------
async def add_vote(issue_id: int, user_id: int, vote: int):
    conn = await get_connection()
    await conn.execute(
        "INSERT OR REPLACE INTO votes (issue_id, user_id, vote) VALUES (?, ?, ?)",
        (issue_id, user_id, vote),
    )
    await conn.commit()
    cur = await conn.execute("SELECT author_id FROM issues WHERE id=?", (issue_id,))
    row = await cur.fetchone()
    if row:
        await add_points(row[0], vote)


async def has_voted(issue_id: int, user_id: int) -> bool:
    conn = await get_connection()
    cur = await conn.execute(
        "SELECT 1 FROM votes WHERE issue_id=? AND user_id=?", (issue_id, user_id)
    )
    return await cur.fetchone() is not None


async def get_votes(issue_id: int) -> int:
    conn = await get_connection()
    cur = await conn.execute("SELECT SUM(vote) FROM votes WHERE issue_id=?", (issue_id,))
    row = await cur.fetchone()
    return row[0] if row and row[0] else 0


async def add_points(user_id: int, points: int):
    conn = await get_connection()
    await conn.execute(
        "INSERT INTO rating (user_id, points, last_updated) VALUES (?, ?, ?) "
        "ON CONFLICT(user_id) DO UPDATE SET points = points + ?, last_updated = ?",
        (user_id, points, datetime.now(), points, datetime.now()),
    )
    await conn.commit()


async def get_points(user_id: int) -> int:
    conn = await get_connection()
    cur = await conn.execute("SELECT points FROM rating WHERE user_id=?", (user_id,))
    row = await cur.fetchone()
    return row[0] if row else 0


async def get_user_rank(points: int) -> int:
    conn = await get_connection()
    cur = await conn.execute("SELECT COUNT(*) FROM rating WHERE points > ?", (points,))
    row = await cur.fetchone()
    return row[0] + 1


async def get_top_users(limit: int = 10):
    conn = await get_connection()
    cur = await conn.execute(
        "SELECT user_id, points FROM rating ORDER BY points DESC LIMIT ?", (limit,)
    )
    return await cur.fetchall()


async def get_author_name_by_id(user_id: int):
    conn = await get_connection()
    cur = await conn.execute(
        "SELECT author_name FROM issues WHERE author_id=? LIMIT 1", (user_id,)
    )
    row = await cur.fetchone()
    return row[0] if row else None


# ---------- Responsible users ----------
async def get_responsible_list():
    conn = await get_connection()
    cur = await conn.execute("SELECT username FROM responsible_users ORDER BY username")
    rows = await cur.fetchall()
    return [row[0] for row in rows]


async def add_responsible(username: str):
    conn = await get_connection()
    await conn.execute(
        "INSERT OR IGNORE INTO responsible_users (username) VALUES (?)", (username,)
    )
    await conn.commit()


async def remove_responsible(username: str):
    conn = await get_connection()
    await conn.execute("DELETE FROM responsible_users WHERE username=?", (username,))
    await conn.commit()


# ---------- Issues: CRUD ----------
async def get_issue_by_id(issue_id: int):
    conn = await get_connection()
    cur = await conn.execute(
        "SELECT id, status, text, author_name, responsible, priority, author_id FROM issues WHERE id=?",
        (issue_id,),
    )
    return await cur.fetchone()


async def get_issue_by_reply(reply_to_message_id: int):
    conn = await get_connection()
    cur = await conn.execute(
        "SELECT id, status FROM issues WHERE message_id=?", (reply_to_message_id,)
    )
    return await cur.fetchone()


async def add_issue(message, issue_type, tags, responsible, priority, file_id="", file_url="", title=""):
    conn = await get_connection()
    cur = await conn.execute(
        """INSERT INTO issues
        (message_id, chat_id, author_id, author_name, username, text, type, tags,
         responsible, priority, created_at, file_id, file_url, title)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            message.message_id, message.chat_id, message.from_user.id,
            message.from_user.full_name, message.from_user.username or "",
            message.text, issue_type, tags, responsible, priority, datetime.now(),
            file_id, file_url, title,
        ),
    )
    await conn.commit()
    issue_id = cur.lastrowid
    await add_audit_log(issue_id, message.from_user.id, "create", "", f"type={issue_type}, priority={priority}")
    return issue_id


async def update_priority(issue_id: int, priority: str, user_id: int):
    conn = await get_connection()
    cur = await conn.execute("SELECT priority FROM issues WHERE id=?", (issue_id,))
    old = await cur.fetchone()
    await conn.execute("UPDATE issues SET priority=? WHERE id=?", (priority, issue_id))
    await conn.commit()
    if old and old[0] != priority:
        await add_audit_log(issue_id, user_id, "change_priority", old[0], priority)


async def close_issue(issue_id: int, closer_id: int = None):
    conn = await get_connection()
    cur = await conn.execute("SELECT status FROM issues WHERE id=?", (issue_id,))
    old = await cur.fetchone()
    if old and old[0] == "closed":
        return False
    if closer_id:
        await conn.execute(
            "UPDATE issues SET status='closed', closed_by=?, closed_at=? WHERE id=?",
            (closer_id, datetime.now(), issue_id),
        )
    else:
        await conn.execute(
            "UPDATE issues SET status='closed', closed_at=? WHERE id=?",
            (datetime.now(), issue_id),
        )
    await conn.commit()
    await add_audit_log(issue_id, closer_id or 0, "close", old[0] if old else "", "closed")
    if closer_id:
        await add_points(closer_id, 2)
    return True


async def reopen_issue(issue_id: int, user_id: int):
    conn = await get_connection()
    cur = await conn.execute("SELECT status FROM issues WHERE id=?", (issue_id,))
    old = await cur.fetchone()
    await conn.execute("UPDATE issues SET status='open', reminder_sent=0 WHERE id=?", (issue_id,))
    await conn.commit()
    await add_audit_log(issue_id, user_id, "reopen", old[0] if old else "", "open")


async def is_issue_resolved(issue_id: int) -> bool:
    conn = await get_connection()
    cur = await conn.execute("SELECT status FROM issues WHERE id=?", (issue_id,))
    row = await cur.fetchone()
    return bool(row and row[0] == "closed")


async def mark_reminder_sent(issue_id: int):
    conn = await get_connection()
    await conn.execute("UPDATE issues SET reminder_sent=1 WHERE id=?", (issue_id,))
    await conn.commit()


async def get_open_issues_without_reminder():
    """Для повторной постановки джоб напоминаний после рестарта бота."""
    conn = await get_connection()
    cur = await conn.execute(
        "SELECT id, chat_id, priority, created_at FROM issues "
        "WHERE status='open' AND (reminder_sent=0 OR reminder_sent IS NULL)"
    )
    return await cur.fetchall()


async def get_stale_open_issues(days: int):
    """Для автозакрытия задач старше N дней."""
    conn = await get_connection()
    cutoff = datetime.now() - timedelta(days=days)
    cur = await conn.execute(
        "SELECT id FROM issues WHERE status='open' AND created_at <= ?", (cutoff,)
    )
    return [row[0] for row in await cur.fetchall()]


# ---------- Comments ----------
async def add_comment(issue_id: int, user_id: int, user_name: str, text: str):
    conn = await get_connection()
    await conn.execute(
        "INSERT INTO comments (issue_id, user_id, user_name, text, created_at) VALUES (?, ?, ?, ?, ?)",
        (issue_id, user_id, user_name, text, datetime.now()),
    )
    await conn.commit()
    await add_audit_log(issue_id, user_id, "comment", "", text)


async def get_comments(issue_id: int):
    conn = await get_connection()
    cur = await conn.execute(
        "SELECT user_name, text, created_at FROM comments WHERE issue_id=? ORDER BY created_at",
        (issue_id,),
    )
    return await cur.fetchall()


# ---------- Tags ----------
async def get_all_tags():
    conn = await get_connection()
    cur = await conn.execute(
        "SELECT DISTINCT tags FROM issues WHERE tags IS NOT NULL AND tags != ''"
    )
    rows = await cur.fetchall()
    tags_set = set()
    for row in rows:
        if row[0]:
            for tag in row[0].split(","):
                if tag:
                    tags_set.add(tag.strip())
    return sorted(tags_set)


def _empty_type_stats():
    return {"bug": {"total": 0, "closed": 0}, "suggestion": {"total": 0, "closed": 0}}


def _fill_type_stats(rows):
    stats = _empty_type_stats()
    for t, status in rows:
        if t not in stats:
            continue
        stats[t]["total"] += 1
        if status == "closed":
            stats[t]["closed"] += 1
    return stats


async def get_stats_by_tag(tag: str, days: int = None):
    conn = await get_connection()
    query = "SELECT type, status FROM issues WHERE tags LIKE ?"
    params = [f"%{tag}%"]
    if days:
        query += " AND created_at >= ?"
        params.append(datetime.now() - timedelta(days=days))
    cur = await conn.execute(query, params)
    return _fill_type_stats(await cur.fetchall())


async def get_user_stats(user_id: int, days: int = None):
    conn = await get_connection()
    query = "SELECT type, status FROM issues WHERE author_id=?"
    params = [user_id]
    if days:
        query += " AND created_at >= ?"
        params.append(datetime.now() - timedelta(days=days))
    cur = await conn.execute(query, params)
    return _fill_type_stats(await cur.fetchall())


async def get_user_stats_by_username(username: str, days: int = None):
    conn = await get_connection()
    query = "SELECT type, status FROM issues WHERE username=?"
    params = [username]
    if days:
        query += " AND created_at >= ?"
        params.append(datetime.now() - timedelta(days=days))
    cur = await conn.execute(query, params)
    return _fill_type_stats(await cur.fetchall())


async def get_stats_responsible(username: str, days: int = None):
    conn = await get_connection()
    query = "SELECT id, status, type FROM issues WHERE responsible LIKE ?"
    params = [f"%{username}%"]
    if days:
        query += " AND created_at >= ?"
        params.append(datetime.now() - timedelta(days=days))
    cur = await conn.execute(query, params)
    rows = await cur.fetchall()
    total = len(rows)
    closed = sum(1 for r in rows if r[1] == "closed")
    bugs = sum(1 for r in rows if r[2] == "bug")
    suggestions = sum(1 for r in rows if r[2] == "suggestion")
    return total, closed, bugs, suggestions


async def search_issues(text_query: str):
    conn = await get_connection()
    cur = await conn.execute(
        "SELECT id, author_name, text, type, status, tags, created_at FROM issues "
        "WHERE text LIKE ? ORDER BY created_at DESC LIMIT 20",
        (f"%{text_query}%",),
    )
    return await cur.fetchall()


async def get_open_tasks(limit=10, priority=None, tag=None, days=None):
    conn = await get_connection()
    query = "SELECT id, author_name, text, type, priority, tags, created_at FROM issues WHERE status='open'"
    params = []
    if priority:
        query += " AND priority=?"
        params.append(priority)
    if tag:
        query += " AND tags LIKE ?"
        params.append(f"%{tag}%")
    if days:
        query += " AND created_at >= ?"
        params.append(datetime.now() - timedelta(days=days))
    query += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)
    cur = await conn.execute(query, params)
    return await cur.fetchall()


async def generate_export(days=None):
    conn = await get_connection()
    query = ("SELECT id, author_name, username, text, type, status, priority, tags, "
              "responsible, created_at FROM issues")
    params = []
    if days:
        query += " WHERE created_at >= ?"
        params.append(datetime.now() - timedelta(days=days))
    cur = await conn.execute(query, params)
    return await cur.fetchall()


async def generate_weekly_report():
    conn = await get_connection()
    week_ago = datetime.now() - timedelta(days=7)
    cur = await conn.execute("SELECT COUNT(*) FROM issues WHERE created_at >= ?", (week_ago,))
    total_created = (await cur.fetchone())[0]
    cur = await conn.execute(
        "SELECT COUNT(*) FROM issues WHERE status='closed' AND created_at >= ?", (week_ago,)
    )
    total_closed = (await cur.fetchone())[0]
    cur = await conn.execute(
        "SELECT type, COUNT(*) FROM issues WHERE created_at >= ? GROUP BY type", (week_ago,)
    )
    type_counts = await cur.fetchall()
    cur = await conn.execute(
        "SELECT priority, COUNT(*) FROM issues WHERE created_at >= ? GROUP BY priority", (week_ago,)
    )
    priority_counts = await cur.fetchall()
    return total_created, total_closed, type_counts, priority_counts


async def get_recent_open_issues_for_similarity(limit=20):
    conn = await get_connection()
    cur = await conn.execute(
        "SELECT id, text, author_name FROM issues WHERE status='open' ORDER BY created_at DESC LIMIT ?",
        (limit,),
    )
    return await cur.fetchall()


async def generate_excel_rows(from_date=None, to_date=None):
    conn = await get_connection()
    query = (
        "SELECT id, title, text, author_name, responsible, created_at, closed_at, priority, tags "
        "FROM issues WHERE status='closed'"
    )
    params = []
    if from_date:
        query += " AND closed_at >= ?"
        params.append(from_date)
    if to_date:
        query += " AND closed_at <= ?"
        params.append(to_date)
    query += " ORDER BY responsible, closed_at"
    cur = await conn.execute(query, params)
    return await cur.fetchall()


async def get_dashboard_data():
    conn = await get_connection()
    week_ago = datetime.now() - timedelta(days=7)
    cur = await conn.execute("SELECT COUNT(*) FROM issues WHERE created_at >= ?", (week_ago,))
    total_created = (await cur.fetchone())[0]
    cur = await conn.execute(
        "SELECT COUNT(*) FROM issues WHERE status='closed' AND created_at >= ?", (week_ago,)
    )
    total_closed = (await cur.fetchone())[0]
    cur = await conn.execute(
        "SELECT priority, COUNT(*) FROM issues WHERE created_at >= ? GROUP BY priority", (week_ago,)
    )
    priority_counts = await cur.fetchall()
    cur = await conn.execute(
        "SELECT tags FROM issues WHERE tags IS NOT NULL AND tags != '' ORDER BY created_at DESC LIMIT 50"
    )
    tags_rows = await cur.fetchall()
    tag_freq = Counter()
    for row in tags_rows:
        if row[0]:
            for tag in row[0].split(","):
                tag = tag.strip()
                if tag:
                    tag_freq[tag] += 1
    top_tags = tag_freq.most_common(5)
    top_users = await get_top_users(5)
    return total_created, total_closed, priority_counts, top_tags, top_users
