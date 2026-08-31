"""
Плановые задачи: напоминания по приоритету, утреннее приветствие,
автозакрытие старых задач.

Отличия от исходной версии:
 - напоминания переживают рестарт бота: при старте (rearm_reminders)
   вычитываются все открытые задачи без отправленного напоминания и для
   них заново ставятся джобы (раньше это хранилось только в bot_data и
   терялось при каждом деплое на Railway).
 - добавлена реально работающая автозакрытие задач (auto_close_job) —
   в исходном коде настройка auto_close_days существовала в БД, но никакая
   джоба её не использовала.
"""
import logging

from telegram.ext import ContextTypes

from bot.config import GROUP_CHAT_ID
from bot.db import repository as repo

logger = logging.getLogger(__name__)


def _get_jobs_dict(context: ContextTypes.DEFAULT_TYPE) -> dict:
    if context.bot_data.get("reminder_jobs") is None:
        context.bot_data["reminder_jobs"] = {}
    return context.bot_data["reminder_jobs"]


async def schedule_reminder(context: ContextTypes.DEFAULT_TYPE, issue_id: int, chat_id: int, minutes: int):
    if not context.job_queue:
        return
    job = context.job_queue.run_once(
        send_reminder, when=minutes * 60, data={"issue_id": issue_id, "chat_id": chat_id}
    )
    _get_jobs_dict(context)[issue_id] = job


async def reschedule_reminder(context: ContextTypes.DEFAULT_TYPE, issue_id: int, chat_id: int, minutes: int):
    if not context.job_queue:
        return
    jobs = _get_jobs_dict(context)
    old = jobs.get(issue_id)
    if old:
        old.schedule_removal()
    await schedule_reminder(context, issue_id, chat_id, minutes)


async def send_reminder(context: ContextTypes.DEFAULT_TYPE):
    data = context.job.data
    issue_id, chat_id = data["issue_id"], data["chat_id"]
    if await repo.is_issue_resolved(issue_id):
        return
    issue = await repo.get_issue_by_id(issue_id)
    if not issue:
        return
    responsible = issue[4] or ""
    await repo.mark_reminder_sent(issue_id)
    mentions = ""
    usernames = [u.strip() for u in responsible.split(",") if u.strip()]
    if usernames:
        mentions = " " + " ".join(f"@{u}" for u in usernames)
    await context.bot.send_message(
        chat_id=chat_id,
        text=f"⚠️ Напоминание! Задача #{issue_id} без ответа.{mentions}\nПросьба ответить.",
    )


async def rearm_reminders_on_startup(application):
    """
    Вызывается один раз при старте бота: заново ставит напоминания для всех
    открытых задач, у которых ещё не было отправлено напоминание. Считаем
    оставшееся время грубо (полный интервал приоритета от старта бота) —
    достаточно для того, чтобы задачи не "терялись" после деплоя.
    """
    from bot.config import PRIORITY_REMINDER_MINUTES

    if not application.job_queue:
        return
    rows = await repo.get_open_issues_without_reminder()
    for issue_id, chat_id, priority, created_at in rows:
        minutes = PRIORITY_REMINDER_MINUTES.get(priority, PRIORITY_REMINDER_MINUTES["low"])
        job = application.job_queue.run_once(
            send_reminder, when=minutes * 60, data={"issue_id": issue_id, "chat_id": chat_id or GROUP_CHAT_ID}
        )
        application.bot_data.setdefault("reminder_jobs", {})[issue_id] = job
    if rows:
        logger.info(f"Переустановлено напоминаний после рестарта: {len(rows)}")


async def morning_greeting(context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_message(
        chat_id=GROUP_CHAT_ID, text="🌞 Доброе утро, коллеги! Желаем продуктивного дня!"
    )
    from bot.utils import PRIORITY_EMOJI

    tasks = await repo.get_open_tasks(limit=10)
    if not tasks:
        await context.bot.send_message(chat_id=GROUP_CHAT_ID, text="🎉 Нет открытых задач!")
        return
    response = "📋 Открытые задачи:\n"
    for issue_id, author, text, issue_type, priority, tags, created in tasks:
        emoji = PRIORITY_EMOJI.get(priority, "")
        created_str = created[:16] if isinstance(created, str) else created.strftime("%Y-%m-%d %H:%M")
        response += f"#{issue_id} {issue_type} {emoji} от {author} ({created_str}): {text[:50]}...\n"
    await context.bot.send_message(chat_id=GROUP_CHAT_ID, text=response)


async def auto_close_job(context: ContextTypes.DEFAULT_TYPE):
    """Ежедневно закрывает задачи старше settings.auto_close_days дней (0 — выключено)."""
    from bot.config import AUTO_CLOSE_DEFAULT_DAYS

    raw = await repo.get_setting("auto_close_days", str(AUTO_CLOSE_DEFAULT_DAYS))
    try:
        days = int(raw)
    except (TypeError, ValueError):
        days = AUTO_CLOSE_DEFAULT_DAYS
    if days <= 0:
        return
    stale_ids = await repo.get_stale_open_issues(days)
    for issue_id in stale_ids:
        await repo.close_issue(issue_id, closer_id=None)
    if stale_ids:
        ids_text = ", ".join(f"#{i}" for i in stale_ids)
        await context.bot.send_message(
            chat_id=GROUP_CHAT_ID,
            text=f"🕐 Автоматически закрыты задачи без активности более {days} дн.: {ids_text}",
        )
        logger.info(f"Автозакрытие: закрыто {len(stale_ids)} задач")
