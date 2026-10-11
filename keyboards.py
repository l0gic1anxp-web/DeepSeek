from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def moderation_kb(user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Отправить", callback_data=f"mod:send:{user_id}"),
        InlineKeyboardButton(text="✏️ Изменить", callback_data=f"mod:edit:{user_id}"),
        InlineKeyboardButton(text="❌ Отклонить", callback_data=f"mod:reject:{user_id}"),
    ]])


def mode_kb(current: str) -> InlineKeyboardMarkup:
    def mark(m: str) -> str:
        return "🟢 " if m == current else ""

    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=f"{mark('chat')}💬 Обычный",
                                 callback_data="mode:chat"),
            InlineKeyboardButton(text=f"{mark('reasoning')}🧠 Рассуждение",
                                 callback_data="mode:reasoning"),
        ],
        [
            InlineKeyboardButton(text=f"{mark('search')}🔍 Поиск",
                                 callback_data="mode:search"),
        ],
        [
            InlineKeyboardButton(text="🗑 Очистить историю",
                                 callback_data="clear_history"),
        ],
    ])
