"""
Админ-команды.

Добавлено относительно исходной версии: /set_auto_close, /ban_user,
/unban_user — раньше эти команды были упомянуты в /help и в БД под них
уже была логика (banned_users, settings.auto_close_days), но сами
CommandHandler'ы нигде не регистрировались, поэтому команды не работали.
"""
from telegram import Update
from telegram.ext import ContextTypes

from bot.config import ADMIN_IDS
from bot.db import repository as repo


def _require_admin(update: Update) -> bool:
    return update.effective_user.id in ADMIN_IDS


async def add_responsible_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _require_admin(update):
        await update.message.reply_text("⛔ Нет прав.")
        return
    if not context.args:
        await update.message.reply_text("Укажите юзернейм: /add_responsible @username")
        return
    username = context.args[0].lstrip("@")
    await repo.add_responsible(username)
    await update.message.reply_text(f"✅ @{username} добавлен.")


async def remove_responsible_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _require_admin(update):
        await update.message.reply_text("⛔ Нет прав.")
        return
    if not context.args:
        await update.message.reply_text("Укажите юзернейм: /remove_responsible @username")
        return
    username = context.args[0].lstrip("@")
    await repo.remove_responsible(username)
    await update.message.reply_text(f"✅ @{username} удалён.")


async def list_responsible_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    list_resp = await repo.get_responsible_list()
    if not list_resp:
        await update.message.reply_text("Список ответственных пуст.")
        return
    await update.message.reply_text("📋 Список ответственных:\n" + "\n".join(f"@{u}" for u in list_resp))


async def set_auto_close_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _require_admin(update):
        await update.message.reply_text("⛔ Нет прав.")
        return
    if not context.args or not context.args[0].isdigit():
        current = await repo.get_setting("auto_close_days", "14")
        await update.message.reply_text(
            f"Текущее автозакрытие: {current} дн.\nИспользование: /set_auto_close <дни>"
        )
        return
    days = context.args[0]
    await repo.set_setting("auto_close_days", days)
    await update.message.reply_text(f"✅ Автозакрытие открытых задач установлено: {days} дн.")


async def ban_user_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _require_admin(update):
        await update.message.reply_text("⛔ Нет прав.")
        return
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("Использование: /ban_user <telegram_id> [причина]")
        return
    user_id = int(context.args[0])
    reason = " ".join(context.args[1:]) if len(context.args) > 1 else ""
    await repo.ban_user(user_id, reason)
    await update.message.reply_text(f"⛔ Пользователь {user_id} забанен." + (f" Причина: {reason}" if reason else ""))


async def unban_user_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _require_admin(update):
        await update.message.reply_text("⛔ Нет прав.")
        return
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("Использование: /unban_user <telegram_id>")
        return
    user_id = int(context.args[0])
    await repo.unban_user(user_id)
    await update.message.reply_text(f"✅ Пользователь {user_id} разбанен.")
