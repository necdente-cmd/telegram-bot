"""
Централизованная конфигурация бота.
Все переменные читаются из окружения (Railway → Variables),
с разумными дефолтами для локальной разработки.
"""
import os
import re


def _get_bool(name: str, default: bool) -> bool:
    val = os.environ.get(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


def _get_int_list(name: str, default: list[int]) -> list[int]:
    val = os.environ.get(name)
    if not val:
        return default
    return [int(x.strip()) for x in val.split(",") if x.strip()]


def _get_str_list(name: str, default: list[str]) -> list[str]:
    val = os.environ.get(name)
    if not val:
        return default
    return [x.strip() for x in val.split(",") if x.strip()]


def _resolve_sqlite_path(database_url: str) -> str:
    """
    Поддерживает DATABASE_URL вида:
      sqlite:////data/support.db   -> /data/support.db  (абсолютный путь, Railway Volume)
      sqlite:///support.db         -> support.db         (относительный путь)
    Если DATABASE_URL не задан или не sqlite:// — используем локальный файл по умолчанию.
    """
    prefix = "sqlite:///"
    if database_url and database_url.startswith(prefix):
        return database_url[len(prefix):]
    return "data/support.db"


# ---------- Telegram ----------
BOT_TOKEN = os.environ.get("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не задан в переменных окружения")

BOT_USERNAME = os.environ.get("BOT_USERNAME", "SANARIOPCLINICMODULSYSTEMA_bot")

GROUP_CHAT_ID = int(os.environ.get("GROUP_CHAT_ID", "-1004381515853"))
ADMIN_IDS = _get_int_list("ADMIN_IDS", [549890508])
DEFAULT_RESPONSIBLE = _get_str_list("DEFAULT_RESPONSIBLE", ["tunduk_dev", "tunduk_analyst"])

# ---------- База данных ----------
DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///data/support.db")
DB_PATH = _resolve_sqlite_path(DATABASE_URL)

# ---------- ИИ (DeepSeek / OpenAI-совместимый) ----------
AI_API_KEY = os.environ.get("AI_API_KEY")
AI_BASE_URL = os.environ.get("AI_BASE_URL", "https://api.deepseek.com")
AI_MODEL = os.environ.get("AI_MODEL", "deepseek-chat")
AI_ENABLED = _get_bool("AI_ENABLED", True) and bool(AI_API_KEY)

# ---------- Расписание ----------
MORNING_TIME_UTC = os.environ.get("MORNING_TIME_UTC", "03:00")
TIMEZONE_OFFSET = int(os.environ.get("TIMEZONE_OFFSET", "6"))

PRIORITY_REMINDER_MINUTES = {
    "high": int(os.environ.get("REMINDER_HIGH_MIN", "5")),
    "medium": int(os.environ.get("REMINDER_MEDIUM_MIN", "15")),
    "low": int(os.environ.get("REMINDER_LOW_MIN", "30")),
}

AUTO_CLOSE_DEFAULT_DAYS = int(os.environ.get("AUTO_CLOSE_DEFAULT_DAYS", "14"))
AUTO_CLOSE_CHECK_HOUR_UTC = os.environ.get("AUTO_CLOSE_CHECK_HOUR_UTC", "02:30")

MENTION_RE = re.compile(r"@(\w+)")
TAG_RE = re.compile(r"#\w+")
