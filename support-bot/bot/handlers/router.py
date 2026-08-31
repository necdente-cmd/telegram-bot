"""
Главный роутер входящих текстовых сообщений группы.

Исправление ключевого бага исходной версии: раньше здесь регистрировались
ДВА отдельных MessageHandler на один и тот же фильтр (TEXT & ~COMMAND) —
в python-telegram-bot в рамках одной группы обрабатывается только первый
подошедший хэндлер, поэтому "ручной ввод ответственного" никогда не
доходил до своего обработчика. Теперь это один хэндлер с явным порядком:
  1) ожидание ручного ввода @username ответственного
  2) бан-проверка
  3) закрытие задачи ответом на исходное сообщение
  4) приветствие / вопросы "кто ты"
  5) классификация ИИ (если включён)
  6) классификация по ключевым словам (fallback)
"""
import logging
import re

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from bot.ai import client as ai
from bot.config import GROUP_CHAT_ID
from bot.db import repository as repo
from bot.handlers.issues import handle_manual_responsible
from bot.utils import is_greeting_or_question

logger = logging.getLogger(__name__)

BUG_PATTERN = re.compile(r"\b(баг|ошибка|bug|не работает|глюк)\b", re.IGNORECASE)
SUGGEST_PATTERN = re.compile(r"\b(предложени|улучшени|suggest|идея|хотелось бы)\b", re.IGNORECASE)
NEGATION_PHRASES = [
    "не баг", "не ошибка", "это не баг", "не предложение", "не улучшение",
    "поясню", "объясню", "просто хочу сказать", "к слову", "кстати",
]


async def offer_issue_creation(msg, text, issue_type, context):
    context.user_data["pending_issue"] = {"message": msg, "text": text, "issue_type": issue_type}
    keyboard = [[
        InlineKeyboardButton("✅ Да, создать", callback_data="confirm_yes"),
        InlineKeyboardButton("❌ Нет, отменить", callback_data="confirm_no"),
    ]]
    await msg.reply_text(
        f"Вы упомянули '{issue_type}'. Создать задачу?",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg or not msg.text or msg.chat_id != GROUP_CHAT_ID:
        return
    text = msg.text

    # 1) Ждём ручной ввод @username ответственного — если апдейт обработан
    # здесь, дальше идти не нужно.
    if await handle_manual_responsible(update, context):
        return

    if await repo.is_banned(msg.from_user.id):
        await msg.reply_text("⛔ Вы забанены.")
        return

    if msg.reply_to_message:
        issue = await repo.get_issue_by_reply(msg.reply_to_message.message_id)
        if issue and issue[1] == "open":
            await repo.close_issue(issue[0], msg.from_user.id)
            await msg.reply_text(f"✅ Задача #{issue[0]} закрыта.")
        return

    if text.startswith("/"):
        return

    from bot.config import BOT_USERNAME
    if f"@{BOT_USERNAME}" in text or is_greeting_or_question(text):
        await msg.reply_text(
            "👋 Привет! Я бот для регистрации багов и предложений.\nИспользуйте /help для списка команд."
        )
        return

    if ai.is_ai_available():
        analysis = await ai.analyze_message(text)
        ai_issue_type = analysis.get("type") if analysis else None
        if ai_issue_type in ("bug", "suggestion"):
            if any(p in text.lower() for p in NEGATION_PHRASES):
                return
            await offer_issue_creation(msg, text, ai_issue_type, context)
            return
        # ИИ сказал "other" — как и в исходной версии, дальше всё равно
        # проверяем по ключевым словам (fallback), а не молчим сразу.

    issue_type = None
    if BUG_PATTERN.search(text):
        issue_type = "bug"
    elif SUGGEST_PATTERN.search(text):
        issue_type = "suggestion"
    else:
        return

    if any(p in text.lower() for p in NEGATION_PHRASES):
        return

    await offer_issue_creation(msg, text, issue_type, context)
