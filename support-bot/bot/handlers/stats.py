"""Статистика: /mystats, /stats, /tags, /tagstats, /stats_responsible."""
from telegram import Update
from telegram.ext import ContextTypes

from bot.config import ADMIN_IDS
from bot.db import repository as repo


def _parse_period_arg(args, index):
    if len(args) > index and args[index].lower() in ("week", "7"):
        return 7
    if len(args) > index and args[index].lower() in ("month", "30"):
        return 30
    return None


def _format_stats(stats, who, period):
    return (
        f"📊 Статистика {who} {period}:\n"
        f"🐛 Баги: {stats['bug']['total']} создано, {stats['bug']['closed']} закрыто\n"
        f"💡 Предложения: {stats['suggestion']['total']} создано, {stats['suggestion']['closed']} закрыто"
    )


async def my_stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.username or "без юзернейма"
    days = _parse_period_arg(context.args, 0)
    stats = await repo.get_user_stats(user_id, days)
    period = "за всё время" if not days else f"за последние {days} дней"
    await update.message.reply_text(_format_stats(stats, f"@{username}", period))


async def stats_username_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("⛔ Нет прав.")
        return
    if not context.args:
        await update.message.reply_text("Укажите юзернейм: /stats @username")
        return
    target = context.args[0].lstrip("@")
    days = _parse_period_arg(context.args, 1)
    stats = await repo.get_user_stats_by_username(target, days)
    if stats["bug"]["total"] == 0 and stats["suggestion"]["total"] == 0:
        await update.message.reply_text(f"Пользователь @{target} не имеет задач.")
        return
    period = "за всё время" if not days else f"за последние {days} дней"
    await update.message.reply_text(_format_stats(stats, f"@{target}", period))


async def tags_list_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tags = await repo.get_all_tags()
    if not tags:
        await update.message.reply_text("📭 Нет тегов.")
        return
    await update.message.reply_text("🏷️ Теги:\n" + "\n".join(tags))


async def tag_stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Укажите тег: /tagstats #модуль")
        return
    tag = context.args[0].strip()
    if not tag.startswith("#"):
        tag = "#" + tag
    days = _parse_period_arg(context.args, 1)
    stats = await repo.get_stats_by_tag(tag, days)
    if stats["bug"]["total"] == 0 and stats["suggestion"]["total"] == 0:
        await update.message.reply_text(f"По тегу {tag} задач нет.")
        return
    period = "за всё время" if not days else f"за последние {days} дней"
    await update.message.reply_text(_format_stats(stats, f"тегу {tag}", period))


async def stats_responsible_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Укажите юзернейм: /stats_responsible @username")
        return
    target = context.args[0].lstrip("@")
    days = _parse_period_arg(context.args, 1)
    total, closed, bugs, suggestions = await repo.get_stats_responsible(target, days)
    period = "за всё время" if not days else f"за последние {days} дней"
    await update.message.reply_text(
        f"📊 Статистика по ответственному @{target} {period}:\n"
        f"📌 Всего: {total}\n✅ Закрыто: {closed}\n🐛 Багов: {bugs}\n💡 Предложений: {suggestions}"
    )


async def rating_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.username or "без юзернейма"
    points = await repo.get_points(user_id)
    rank = await repo.get_user_rank(points)
    await update.message.reply_text(
        f"📊 Ваш рейтинг:\nПользователь: @{username}\nОчки: {points}\nПозиция в топе: {rank}"
    )


async def top_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    top_users = await repo.get_top_users(10)
    if not top_users:
        await update.message.reply_text("Пока нет рейтинга.")
        return
    response = "🏆 Топ-10 пользователей:\n"
    for i, (uid, pts) in enumerate(top_users, 1):
        name = await repo.get_author_name_by_id(uid) or f"user_{uid}"
        response += f"{i}. {name} – {pts} очков\n"
    await update.message.reply_text(response)
