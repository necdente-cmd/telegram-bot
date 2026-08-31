"""
Создание задач (bug/suggestion), выбор приоритета и ответственного, голосование.

Исправленные баги относительно исходной версии:
 - callback_data для приоритета парсится по префиксу (startswith), а не по
   индексу после split('_') — раньше кнопка "Пропустить" падала с IndexError.
 - выбор username через "resp_<username>" использует split('_', 1), чтобы не
   обрезать юзернеймы, содержащие "_".
 - текст сообщения больше не подменяется (msg.text = ...) — передаём text
   отдельным аргументом, это надёжнее при повторной обработке апдейта.
 - ручной ввод ответственного (@username в свободном тексте) больше не
   "проглатывается" другим хэндлером — см. handlers/router.py.
"""
import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from bot.ai import client as ai
from bot.config import ADMIN_IDS, DEFAULT_RESPONSIBLE, PRIORITY_REMINDER_MINUTES
from bot.db import repository as repo
from bot.utils import PRIORITY_EMOJI, extract_mentions, extract_tags
from bot.jobs.scheduler import schedule_reminder, reschedule_reminder

logger = logging.getLogger(__name__)


async def find_similar_issues(text: str, limit: int = 3):
    rows = await repo.get_recent_open_issues_for_similarity(limit=20)
    if not rows:
        return []
    import re
    words = set(re.findall(r"\w+", text.lower()))
    scored = []
    for issue_id, issue_text, author in rows:
        common = len(words & set(re.findall(r"\w+", issue_text.lower())))
        if common > 1:
            scored.append((common, issue_id, issue_text[:50], author))
    scored.sort(reverse=True)
    return scored[:limit]


async def create_issue(msg, text: str, issue_type: str, context: ContextTypes.DEFAULT_TYPE, responsible=None):
    title = await ai.generate_title(text)
    tags_list = extract_tags(text)

    if ai.is_ai_available() and not tags_list:
        ai_tags = await ai.auto_tagging(text)
        if ai_tags:
            tags_list = ai_tags
    tags_str = ",".join(tags_list) if tags_list else ""

    priority = await ai.smart_priority(text)

    if responsible is None:
        mentions = extract_mentions(text)
        responsible = mentions if mentions else DEFAULT_RESPONSIBLE
    responsible_str = ",".join(responsible)

    file_id, file_url = "", ""
    if msg.document:
        file_id = msg.document.file_id
        file_url = msg.document.file_name or "документ"
    elif msg.photo:
        file_id = msg.photo[-1].file_id
        file_url = "фото"

    issue_id = await repo.add_issue(msg, issue_type, tags_str, responsible_str, priority, file_id, file_url, title)
    await repo.add_points(msg.from_user.id, 1)

    responsible_mentions = " ".join(f"@{u}" for u in responsible)
    tag_text = f"🏷️ Теги: {', '.join(tags_list)}" if tags_list else ""
    priority_emoji = PRIORITY_EMOJI.get(priority, "")
    minutes = PRIORITY_REMINDER_MINUTES[priority]
    file_text = f"📎 Вложение: {file_url}" if file_url else ""

    similar = await find_similar_issues(text, limit=3)
    similar_text = ""
    if similar:
        similar_text = "\n⚠️ Похожие открытые задачи:\n" + "".join(
            f"  #{sid} ({sauthor}): {stext}...\n" for _, sid, stext, sauthor in similar
        )

    vote_buttons = []
    if issue_type == "suggestion":
        vote_buttons = [
            InlineKeyboardButton("👍", callback_data=f"vote_{issue_id}_1"),
            InlineKeyboardButton("👎", callback_data=f"vote_{issue_id}_-1"),
        ]

    await msg.reply_text(
        f"🔔 Зарегистрирован {issue_type} #{issue_id}\n"
        f"Заголовок: {title}\n"
        f"Автор: {msg.from_user.full_name}\n"
        f"Текст: {text[:100]}...\n"
        f"{tag_text}\n"
        f"Приоритет: {priority_emoji} {priority}\n"
        f"Ответственные: {responsible_mentions}\n"
        f"⏳ Напоминание через {minutes} мин.\n"
        f"{file_text}\n"
        f"{similar_text}",
        reply_markup=InlineKeyboardMarkup([vote_buttons]) if vote_buttons else None,
    )

    if priority == "high":
        for user in responsible:
            try:
                await context.bot.send_message(
                    chat_id=user,
                    text=f"🚨 Критичная задача #{issue_id}!\n{title}\n{text[:200]}...\nОтветственные: {responsible_mentions}",
                )
            except Exception:
                pass

    priority_keyboard = [
        [
            InlineKeyboardButton("🔴 Критичный", callback_data=f"set_priority_{issue_id}_high"),
            InlineKeyboardButton("🟡 Важный", callback_data=f"set_priority_{issue_id}_medium"),
            InlineKeyboardButton("🟢 Обычный", callback_data=f"set_priority_{issue_id}_low"),
        ],
        [InlineKeyboardButton("⏩ Пропустить", callback_data=f"skip_priority_{issue_id}")],
    ]
    await msg.reply_text(
        "Выберите приоритет задачи или нажмите 'Пропустить':",
        reply_markup=InlineKeyboardMarkup(priority_keyboard),
    )

    await schedule_reminder(context, issue_id, msg.chat_id, minutes)
    return issue_id


async def priority_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = query.from_user.id

    if data.startswith("set_priority_"):
        rest = data[len("set_priority_"):]
        issue_id_str, new_priority = rest.rsplit("_", 1)
        issue_id = int(issue_id_str)
    elif data.startswith("skip_priority_"):
        issue_id = int(data[len("skip_priority_"):])
        new_priority = None
    else:
        await query.edit_message_text("❌ Неверный формат.")
        return

    issue = await repo.get_issue_by_id(issue_id)
    if not issue:
        await query.edit_message_text("❌ Задача не найдена.")
        return
    author_id = issue[6]
    if user_id != author_id and user_id not in ADMIN_IDS:
        await query.edit_message_text("⛔ Нет прав.")
        return

    if new_priority is None:
        await query.edit_message_text(f"⏩ Приоритет задачи #{issue_id} оставлен как авто.")
        return

    await repo.update_priority(issue_id, new_priority, user_id)
    emoji = PRIORITY_EMOJI.get(new_priority, "")
    await query.edit_message_text(f"✅ Приоритет задачи #{issue_id} изменён на {emoji} {new_priority}.")
    minutes = PRIORITY_REMINDER_MINUTES[new_priority]
    await reschedule_reminder(context, issue_id, query.message.chat_id, minutes)


async def confirm_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    pending = context.user_data.get("pending_issue")
    if not pending:
        await query.edit_message_text("❌ Запрос устарел.")
        return
    if query.from_user.id != pending["message"].from_user.id:
        await query.edit_message_text("⛔ Только автор может подтвердить.")
        return
    if query.data == "confirm_yes":
        await show_responsible_selection(context, query, pending)
    else:
        await query.edit_message_text("❌ Создание отменено.")
        context.user_data.pop("pending_issue", None)


async def show_responsible_selection(context, query, pending):
    responsible_list = await repo.get_responsible_list()
    if not responsible_list:
        responsible_list = DEFAULT_RESPONSIBLE
        for username in responsible_list:
            await repo.add_responsible(username)

    buttons, row = [], []
    for username in responsible_list:
        row.append(InlineKeyboardButton(f"@{username}", callback_data=f"resp_{username}"))
        if len(row) == 3:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([InlineKeyboardButton("✏️ Другой (ввести @username)", callback_data="resp_other")])
    buttons.append([InlineKeyboardButton("⏩ Пропустить", callback_data="resp_skip")])

    context.user_data["pending_responsible"] = {"pending": pending}
    await query.edit_message_text(
        "Выберите ответственного за задачу (можно только одного):",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def responsible_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = query.from_user.id

    pending_data = context.user_data.get("pending_responsible")
    if not pending_data:
        await query.edit_message_text("❌ Сессия истекла.")
        return
    pending = pending_data["pending"]
    issue_type = pending["issue_type"]
    msg = pending["message"]
    text = pending["text"]

    if msg.from_user.id != user_id:
        await query.edit_message_text("⛔ Только автор может выбирать.")
        return

    if data == "resp_skip":
        mentions = extract_mentions(text)
        if mentions:
            responsible = mentions
        else:
            responsible_list = await repo.get_responsible_list()
            responsible = [responsible_list[0]] if responsible_list else DEFAULT_RESPONSIBLE
        await query.edit_message_text("✅ Создаю задачу...")
        await create_issue(msg, text, issue_type, context, responsible)
        context.user_data.pop("pending_responsible", None)
        context.user_data.pop("pending_issue", None)

    elif data == "resp_other":
        await query.edit_message_text(
            "✏️ Напишите в ответ на это сообщение @username ответственного (можно несколько через пробел)."
        )
        context.user_data["awaiting_responsible"] = True

    elif data.startswith("resp_"):
        username = data.split("_", 1)[1]
        responsible = [username]
        await query.edit_message_text(f"✅ Выбран @{username}. Создаю задачу...")
        await create_issue(msg, text, issue_type, context, responsible)
        context.user_data.pop("pending_responsible", None)
        context.user_data.pop("pending_issue", None)


async def handle_manual_responsible(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """
    Возвращает True, если апдейт обработан здесь (и роутер не должен
    передавать его дальше как обычное текстовое сообщение).
    """
    if not context.user_data.get("awaiting_responsible"):
        return False
    msg = update.message
    text = msg.text.strip()
    mentions = extract_mentions(text)
    if not mentions:
        await msg.reply_text("⚠️ Не найдено @username. Попробуйте ещё раз.")
        return True

    pending_data = context.user_data.get("pending_responsible")
    if not pending_data:
        context.user_data.pop("awaiting_responsible", None)
        return True
    pending = pending_data["pending"]

    await msg.reply_text(f"✅ Выбраны: {' '.join(f'@{u}' for u in mentions)}. Создаю задачу...")
    await create_issue(pending["message"], pending["text"], pending["issue_type"], context, mentions)

    context.user_data.pop("awaiting_responsible", None)
    context.user_data.pop("pending_responsible", None)
    context.user_data.pop("pending_issue", None)
    return True


async def vote_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    parts = query.data.split("_")
    if len(parts) < 3:
        return
    issue_id, vote = int(parts[1]), int(parts[2])
    user_id = query.from_user.id

    if await repo.has_voted(issue_id, user_id):
        await query.edit_message_text("❌ Вы уже голосовали.")
        return

    await repo.add_vote(issue_id, user_id, vote)
    total = await repo.get_votes(issue_id)
    await query.edit_message_text(f"✅ Голос учтён! Рейтинг: {total}")
