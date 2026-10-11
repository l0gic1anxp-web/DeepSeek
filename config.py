import os

# ═══════════════════════════════════════════════════
# НАСТРОЙКИ БОТА
# ═══════════════════════════════════════════════════

BOT_TOKEN = "8647935282:AAEuEUCa5EKpbOnjc0oM44nT4WJnoR09ZT8"
ADMIN_ID = 7928733927

AI_API_KEY = "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"
AI_BASE_URL = "https://openrouter.ai/api/v1"
AI_MODEL = "deepseek/deepseek-chat-v3.1:free"
AI_REASONING_MODEL = "deepseek/deepseek-r1:free"

DB_PATH = "bot.db"

ADMIN_TIMEOUT = 30
MAX_HISTORY_CHARS = 12000
USER_COOLDOWN = 2

# ═══════════════════════════════════════════════════
# ВАЛИДАЦИЯ
# ═══════════════════════════════════════════════════

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN не задан")
if not AI_API_KEY:
    raise RuntimeError("AI_API_KEY не задан")
if not ADMIN_ID:
    raise RuntimeError("ADMIN_ID не задан")
