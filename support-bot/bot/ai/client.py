"""
Асинхронный ИИ-клиент (DeepSeek / любой OpenAI-совместимый эндпоинт).

Отличие от исходной версии: используется AsyncOpenAI и await вместо
синхронного OpenAI-клиента, поэтому обращения к ИИ больше не блокируют
event loop бота (раньше на время запроса к DeepSeek "замирали" все
остальные пользователи).
"""
import json
import logging
import re

from openai import AsyncOpenAI

from bot.config import AI_API_KEY, AI_BASE_URL, AI_ENABLED, AI_MODEL
from bot.utils import detect_priority

logger = logging.getLogger(__name__)

# ДИАГНОСТИКА: вывод в консоль, чтобы увидеть в логах
print("🚀 client.py imported")

_client: AsyncOpenAI | None = None
if AI_ENABLED:
    try:
        _client = AsyncOpenAI(api_key=AI_API_KEY, base_url=AI_BASE_URL)
        logger.info("AI клиент инициализирован")
    except Exception as e:
        logger.error(f"Ошибка инициализации AI: {e}")
        _client = None
else:
    logger.warning("AI_API_KEY не задан или AI_ENABLED=false, ИИ-функции отключены")


def is_ai_available() -> bool:
    return _client is not None


async def analyze_message(text: str) -> dict:
    if _client is None:
        return {"type": "other", "reason": "AI недоступен"}
    try:
        response = await _client.chat.completions.create(
            model=AI_MODEL,
            messages=[
                {"role": "system", "content": (
                    "Ты — классификатор сообщений для IT-команды.\n"
                    "Проанализируй сообщение и определи его тип:\n"
                    "- \"bug\": если пользователь сообщает об ошибке, проблеме или неработающей функции.\n"
                    "- \"suggestion\": если пользователь вносит предложение по улучшению, новую идею.\n"
                    "- \"other\": если сообщение не относится к первым двум категориям.\n"
                    "Ответь ТОЛЬКО в формате JSON: {\"type\": \"тип\", \"reason\": \"краткая причина\"}."
                )},
                {"role": "user", "content": text},
            ],
            response_format={"type": "json_object"},
        )
        return json.loads(response.choices[0].message.content)
    except Exception as e:
        logger.error(f"AI ошибка классификации: {e}")
        return {"type": "other", "reason": "Ошибка анализа"}


async def answer_question(question: str) -> str:
    if _client is None:
        return "❌ AI не настроен."
    if len(question) > 500:
        return "⚠️ Вопрос слишком длинный (макс. 500 символов)."
    try:
        response = await _client.chat.completions.create(
            model=AI_MODEL,
            messages=[
                {"role": "system", "content": "Ты — полезный и информативный ассистент."},
                {"role": "user", "content": question},
            ],
        )
        return response.choices[0].message.content
    except Exception as e:
        logger.error(f"AI ответ ошибка: {e}")
        return "❌ Ошибка при обработке вопроса."


async def generate_title(text: str) -> str:
    if _client is None:
        return text[:50] + "..."
    try:
        response = await _client.chat.completions.create(
            model=AI_MODEL,
            messages=[
                {"role": "system", "content": (
                    "Сформулируй краткий заголовок для задачи (максимум 10 слов) "
                    "на основе текста. Ответь только заголовком, без пояснений."
                )},
                {"role": "user", "content": text},
            ],
        )
        return response.choices[0].message.content.strip()
    except Exception:
        return text[:50] + "..."


async def auto_tagging(text: str) -> list[str]:
    if _client is None:
        return []
    try:
        response = await _client.chat.completions.create(
            model=AI_MODEL,
            messages=[
                {"role": "system", "content": (
                    "Ты — система автоматического тегирования. Проанализируй текст и "
                    "предложи 2-5 хэштегов (начинающихся с #) через запятую. "
                    "Ответь только тегами, без пояснений."
                )},
                {"role": "user", "content": text},
            ],
        )
        tags = response.choices[0].message.content.strip()
        return re.findall(r"#\w+", tags)
    except Exception:
        return []


async def smart_priority(text: str) -> str:
    if _client is None:
        return detect_priority(text)
    try:
        response = await _client.chat.completions.create(
            model=AI_MODEL,
            messages=[
                {"role": "system", "content": (
                    "Определи приоритет задачи: high (критично), medium (важно), "
                    "low (обычное). Ответь только одним словом."
                )},
                {"role": "user", "content": text},
            ],
        )
        p = response.choices[0].message.content.strip().lower()
        return p if p in ("high", "medium", "low") else detect_priority(text)
    except Exception:
        return detect_priority(text)


def strip_markdown(text: str) -> str:
    cleaned = re.sub(r"\*\*(.*?)\*\*", r"\1", text)
    cleaned = re.sub(r"\*(.*?)\*", r"\1", cleaned)
    cleaned = re.sub(r"_(.*?)_", r"\1", cleaned)
    cleaned = re.sub(r"#{1,6}\s?", "", cleaned)
    cleaned = re.sub(r"`(.*?)`", r"\1", cleaned)
    cleaned = re.sub(r"\[(.*?)\]\(.*?\)", r"\1", cleaned)
    return cleaned.replace("*", "")
