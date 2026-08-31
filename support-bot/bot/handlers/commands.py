"""
Команды, напрямую работающие с задачами: /bug, /suggest, /priority, /close,
/reopen, /comment, /find.

Исправление: /bug и /suggest больше не подменяют msg.text (в исходной
версии это была хрупкая мутация объекта Message) — текст передаётся
отдельным аргументом в create_issue().
"""
from telegram import Update
from telegram.ext import ContextTypes

from bot.config import ADMIN_IDS, GROUP_CHAT_ID, PRIORITY_REMINDER_MINUTES
from bot.db import repository as repo
from bot.handlers.issues import create_issue
from bot.jobs.scheduler import reschedule_reminder
from bot.utils import PRIORITY_EMOJI


async def bug_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg or not msg.text or msg.chat_id != GROUP_CHAT_ID:
        return
    text = msg.text.replace("/bug", "", 1).strip()
    if not text:
        await msg.reply_text("Укажите описание: /bug описание")
        return
    await create_issue(msg, text, "bug", context)


async def suggest_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg or not msg.text or msg.chat_id != GROUP_CHAT_ID:
        return
    text = msg.text.replace("/suggest", "", 1).strip()
    if not text:
        await msg.reply_text("Укажите описание: /suggest описание")
        return
    await create_issue(msg, text, "suggestion", context)


async def priority_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if len(context.args) < 2:
        await msg.reply_text("Использование: /priority <id> <high|medium|low>")
        return
    try:
        issue_id = int(context.args[0])
    except ValueError:
        await msg.reply_text("Некорректный ID.")
        return
    pr = context.args[1].lower()
    if pr not in ("high", "medium", "low"):
        await msg.reply_text("Приоритет: high, medium или low")
        return
    issue = await repo.get_issue_by_id(issue_id)
    if not issue:
        await msg.reply_text(f"Задача #{issue_id} не найдена.")
        return
    author_id = issue[6]
    user_id = update.effective_user.id
    if user_id != author_id and user_id not in ADMIN_IDS:
        await msg.reply_text("⛔ Нет прав.")
        return
    await repo.update_priority(issue_id, pr, user_id)
    emoji = PRIORITY_EMOJI.get(pr, "")
    await msg.reply_text(f"✅ Приоритет задачи #{issue_id} изменён на {emoji} {pr}.")
    minutes = PRIORITY_REMINDER_MINUTES[pr]
    await reschedule_reminder(context, issue_id, GROUP_CHAT_ID, minutes)


async def close_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Укажите ID: /close 3")
        return
    try:
        issue_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Некорректный ID.")
        return
    issue = await repo.get_issue_by_id(issue_id)
    if not issue:
        await update.message.reply_text(f"Задача #{issue_id} не найдена.")
        return
    if issue[1] == "closed":
        await update.message.reply_text(f"Задача #{issue_id} уже закрыта.")
        return
    await repo.close_issue(issue_id, update.effective_user.id)
    await update.message.reply_text(f"✅ Задача #{issue_id} закрыта.")


async def reopen_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Укажите ID: /reopen 3")
        return
    try:
        issue_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Некорректный ID.")
        return
    issue = await repo.get_issue_by_id(issue_id)
    if not issue:
        await update.message.reply_text(f"Задача #{issue_id} не найдена.")
        return
    if issue[1] == "open":
        await update.message.reply_text(f"Задача #{issue_id} уже открыта.")
        return
    await repo.reopen_issue(issue_id, update.effective_user.id)
    await update.message.reply_text(f"🔄 Задача #{issue_id} открыта заново.")


async def comment_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        await update.message.reply_text("Укажите ID и текст: /comment 3 текст")
        return
    try:
        issue_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Некорректный ID.")
        return
    text = " ".join(context.args[1:])
    issue = await repo.get_issue_by_id(issue_id)
    if not issue:
        await update.message.reply_text(f"Задача #{issue_id} не найдена.")
        return
    user = update.effective_user
    await repo.add_comment(issue_id, user.id, user.full_name or user.username, text)
    await update.message.reply_text(f"💬 Комментарий к задаче #{issue_id} добавлен.")


async def find_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Укажите текст: /find текст")
        return
    query = " ".join(context.args)
    rows = await repo.search_issues(query)
    if not rows:
        await update.message.reply_text("Ничего не найдено.")
        return
    response = "🔍 Результаты:\n"
    for issue_id, author, text, issue_type, status, tags, created in rows:
        emoji = "✅" if status == "closed" else "❌"
        created_str = created[:16] if isinstance(created, str) else created.strftime("%Y-%m-%d %H:%M")
        tag_display = f" {tags}" if tags else ""
        response += f"#{issue_id} {issue_type} {emoji} от {author} ({created_str}): {text[:50]}...{tag_display}\n"
    await update.message.reply_text(response)


async def open_tasks_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    priority = tag = days = None
    for arg in context.args:
        if arg.startswith("#"):
            tag = arg
        elif arg.lower() in ("high", "medium", "low"):
            priority = arg.lower()
        elif arg.lower() in ("today", "day"):
            days = 1
        elif arg.lower() in ("week", "7"):
            days = 7
        elif arg.lower() in ("month", "30"):
            days = 30
    rows = await repo.get_open_tasks(limit=10, priority=priority, tag=tag, days=days)
    if not rows:
        await update.message.reply_text("📭 Нет открытых задач по заданным фильтрам.")
        return
    response = "📋 Открытые задачи:\n"
    for issue_id, author, text, issue_type, priority, tags, created in rows:
        emoji = PRIORITY_EMOJI.get(priority, "")
        created_str = created[:16] if isinstance(created, str) else created.strftime("%Y-%m-%d %H:%M")
        response += f"#{issue_id} {issue_type} {emoji} от {author} ({created_str}): {text[:50]}...\n"
    await update.message.reply_text(response)
