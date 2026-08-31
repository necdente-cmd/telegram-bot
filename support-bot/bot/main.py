"""
Точка входа. Регистрирует все хэндлеры, инициализирует БД, планирует
регулярные джобы и запускает polling.

Отличия от исходной версии:
 - есть общий error_handler (раньше необработанные исключения просто
   терялись в логах, апдейт "зависал" молча для пользователя)
 - при старте переустанавливаются напоминания для открытых задач
   (см. bot.jobs.scheduler.rearm_reminders_on_startup)
 - добавлена ежедневная джоба автозакрытия задач
 - только ОДИН MessageHandler на текстовые сообщения группы (bot.handlers.router),
   который сам решает, кому передать апдейт — вместо двух хэндлеров в одной
   group, из-за чего часть логики раньше не выполнялась
"""
import logging
from datetime import datetime, time

from telegram import Update
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters

from bot.config import (
    ADMIN_IDS, AUTO_CLOSE_CHECK_HOUR_UTC, AUTO_CLOSE_DEFAULT_DAYS, BOT_TOKEN,
    DEFAULT_RESPONSIBLE, MORNING_TIME_UTC,
)

from bot.config import AI_API_KEY, AI_ENABLED
print(f"🔍 MAIN: AI_API_KEY = {'SET' if AI_API_KEY else 'EMPTY'}, AI_ENABLED = {AI_ENABLED}")

from bot.db.connection import init_db
from bot.handlers import admin, commands, issues, misc, reports, router, stats
from bot.jobs.scheduler import auto_close_job, morning_greeting, rearm_reminders_on_startup

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error("Необработанное исключение при обработке апдейта:", exc_info=context.error)
    if ADMIN_IDS:
        try:
            await context.bot.send_message(
                chat_id=ADMIN_IDS[0],
                text=f"⚠️ Ошибка в боте: {context.error}",
            )
        except Exception:
            pass


async def post_init(application: Application):
    await init_db(DEFAULT_RESPONSIBLE, AUTO_CLOSE_DEFAULT_DAYS)
    await application.bot.delete_webhook()
    await rearm_reminders_on_startup(application)
    logger.info("Бот инициализирован и готов к работе")


def _parse_hhmm(value: str) -> time:
    return datetime.strptime(value, "%H:%M").time()


def build_application() -> Application:
    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()

    # Групповые сообщения — единая точка входа
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, misc.greet_new_member))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, router.handle_message))

    # Callback-кнопки
    app.add_handler(CallbackQueryHandler(
        issues.priority_callback, pattern=r"^(set_priority_\d+_(high|medium|low)|skip_priority_\d+)$"
    ))
    app.add_handler(CallbackQueryHandler(issues.confirm_callback, pattern="^(confirm_yes|confirm_no)$"))
    app.add_handler(CallbackQueryHandler(issues.responsible_callback, pattern=r"^(resp_.+|resp_skip|resp_other)$"))
    app.add_handler(CallbackQueryHandler(issues.vote_callback, pattern=r"^vote_\d+_[-\d]+$"))

    # Команды — задачи
    app.add_handler(CommandHandler("bug", commands.bug_command))
    app.add_handler(CommandHandler("suggest", commands.suggest_command))
    app.add_handler(CommandHandler("priority", commands.priority_command))
    app.add_handler(CommandHandler("close", commands.close_command))
    app.add_handler(CommandHandler("reopen", commands.reopen_command))
    app.add_handler(CommandHandler("comment", commands.comment_command))
    app.add_handler(CommandHandler("find", commands.find_command))
    app.add_handler(CommandHandler("open", commands.open_tasks_command))

    # Команды — статистика
    app.add_handler(CommandHandler("mystats", stats.my_stats_command))
    app.add_handler(CommandHandler("stats", stats.stats_username_command))
    app.add_handler(CommandHandler("tags", stats.tags_list_command))
    app.add_handler(CommandHandler("tagstats", stats.tag_stats_command))
    app.add_handler(CommandHandler("stats_responsible", stats.stats_responsible_command))
    app.add_handler(CommandHandler("rating", stats.rating_command))
    app.add_handler(CommandHandler("top", stats.top_command))

    # Команды — отчёты
    app.add_handler(CommandHandler("export", reports.export_command))
    app.add_handler(CommandHandler("report", reports.report_command))
    app.add_handler(CommandHandler("report_pdf", reports.report_pdf_command))
    app.add_handler(CommandHandler("report_excel", reports.report_excel_command))
    app.add_handler(CommandHandler("dashboard", reports.dashboard_command))

    # Команды — прочее
    app.add_handler(CommandHandler("joke", misc.joke_command))
    app.add_handler(CommandHandler("ask", misc.ask_command))
    app.add_handler(CommandHandler("help", misc.help_command))
    app.add_handler(CommandHandler("start", misc.help_command))

    # Команды — админ
    app.add_handler(CommandHandler("add_responsible", admin.add_responsible_command))
    app.add_handler(CommandHandler("remove_responsible", admin.remove_responsible_command))
    app.add_handler(CommandHandler("list_responsible", admin.list_responsible_command))
    app.add_handler(CommandHandler("set_auto_close", admin.set_auto_close_command))
    app.add_handler(CommandHandler("ban_user", admin.ban_user_command))
    app.add_handler(CommandHandler("unban_user", admin.unban_user_command))

    app.add_error_handler(error_handler)

    if app.job_queue:
        try:
            app.job_queue.run_daily(morning_greeting, time=_parse_hhmm(MORNING_TIME_UTC), days=tuple(range(7)))
            app.job_queue.run_daily(auto_close_job, time=_parse_hhmm(AUTO_CLOSE_CHECK_HOUR_UTC), days=tuple(range(7)))
        except Exception as e:
            logger.error(f"Ошибка планирования ежедневных джоб: {e}")
    else:
        logger.warning("JobQueue не инициализирован (нужен extra: python-telegram-bot[job-queue])")

    return app


def main():
    app = build_application()
    logger.info("Бот запущен!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
