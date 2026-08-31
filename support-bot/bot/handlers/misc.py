"""Прочие команды: /ask, /joke, /help, приветствие новых участников."""
from telegram import Update
from telegram.ext import ContextTypes

from bot.ai import client as ai
from bot.utils import get_random_joke

HELP_TEXT = """
🤖 Доступные команды:

/bug <описание> – создать баг
/suggest <описание> – создать предложение
/ask <вопрос> – задать вопрос ИИ
/mystats – ваша статистика
/stats @user – статистика пользователя (админ)
/tags – все теги
/tagstats #тег – статистика по тегу
/open [high|medium|low] [#тег] [today|week|month] – открытые задачи с фильтрами
/close <id> – закрыть задачу
/reopen <id> – открыть заново
/comment <id> текст – комментарий
/find текст – поиск
/priority <id> <high|medium|low> – изменить приоритет
/stats_responsible @user – статистика по ответственному
/export – выгрузить CSV
/report – отчёт за неделю
/report_pdf – отчёт в PDF
/report_excel [from YYYY-MM-DD] [to YYYY-MM-DD] – отчёт в Excel по закрытым задачам
/joke – анекдот
/rating – ваш рейтинг
/top – топ-10 пользователей
/dashboard – дашборд (HTML)

Админские команды:
/add_responsible @user – добавить ответственного
/remove_responsible @user – удалить ответственного
/list_responsible – список ответственных
/set_auto_close <дни> – автозакрытие через N дней
/ban_user <id> [причина] – забанить пользователя
/unban_user <id> – разбанить
/help – это сообщение
"""


async def joke_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"😂 {get_random_joke()}")


async def ask_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("❓ Напишите вопрос после команды: /ask ваш вопрос")
        return
    question = " ".join(context.args)
    if len(question) > 500:
        await update.message.reply_text("⚠️ Вопрос слишком длинный (макс. 500 символов).")
        return
    await update.message.reply_text("🤔 Думаю...")
    answer = await ai.answer_question(question)
    await update.message.reply_text(ai.strip_markdown(answer))


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(HELP_TEXT)


async def greet_new_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    for member in update.message.new_chat_members:
        if member.id == context.bot.id:
            continue
        await update.message.reply_text(
            f"👋 Добро пожаловать, {member.full_name}!\n\nДля справки используйте /help."
        )
