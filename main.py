import asyncio
import logging
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.types import CallbackQuery
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramRetryAfter, TelegramBadRequest

from config import (
    BOT_TOKEN, ADMIN_ID,
    ADMIN_TIMEOUT, MAX_HISTORY_CHARS, USER_COOLDOWN,
)
from db import (
    init_db, upsert_user, save_message, get_history,
    get_user_mode, set_user_mode, clear_history, DB,
)
from ai import ask_ai_stream, build_system_prompt
from formatter import (
    md_to_html, split_message, split_reasoning, sanitize_user_input,
)
from keyboards import moderation_kb, mode_kb

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

processing_users: set[int] = set()
last_request: dict[int, float] = {}
# message_id у админа -> данные заявки
pending: dict[int, dict] = {}


@dp.message(Command("start"))
async def cmd_start(msg: types.Message):
    await upsert_user(msg.from_user.id, msg.from_user.username, msg.from_user.full_name)

    if msg.from_user.id == ADMIN_ID:
        await msg.answer(
            "👋 <b>Привет, админ!</b>\n\n"
            "Диалоги пользователей будут приходить сюда.\n"
            f"Если не ответишь за <b>{ADMIN_TIMEOUT} сек</b> — "
            "ответ уйдёт автоматически.\n\n"
            "<b>Команды:</b> /log, /users, /mode"
        )
        return

    mode = await get_user_mode(msg.from_user.id)
    await msg.answer(
        f"👋 <b>Привет, {msg.from_user.full_name}!</b>\n\n"
        "Я умный ИИ-ассистент. Помогу с вопросами, текстами, кодом, переводом.\n\n"
        "🎛 <b>Режимы:</b>\n"
        "• 💬 <b>Обычный</b> — быстрые ответы\n"
        "• 🧠 <b>Рассуждение</b> — думаю пошагово\n"
        "• 🔍 <b>Поиск</b> — структурированные справки\n\n"
        "⚠️ Работаю <b>только с текстом</b>. Фото, стикеры, файлы, "
        "голосовые не вижу — опиши словами.\n\n"
        "Напиши мне что-нибудь 👇",
        reply_markup=mode_kb(mode),
    )


@dp.message(Command("mode"))
async def cmd_mode(msg: types.Message):
    mode = await get_user_mode(msg.from_user.id)
    await msg.answer("🎛 <b>Выбери режим:</b>", reply_markup=mode_kb(mode))


@dp.callback_query(F.data.startswith("mode:"))
async def on_mode(cb: CallbackQuery):
    mode = cb.data.split(":")[1]
    if mode not in ("chat", "reasoning", "search"):
        await cb.answer("Неизвестный режим")
        return
    await set_user_mode(cb.from_user.id, mode)
    names = {"chat": "💬 Обычный", "reasoning": "🧠 Рассуждение", "search": "🔍 Поиск"}
    await cb.answer(f"Режим: {names[mode]}")
    await cb.message.edit_reply_markup(reply_markup=mode_kb(mode))


@dp.callback_query(F.data == "clear_history")
async def on_clear(cb: CallbackQuery):
    await clear_history(cb.from_user.id)
    await cb.answer("🗑 История очищена", show_alert=True)


@dp.message(
    F.photo | F.sticker | F.voice | F.video | F.document
    | F.audio | F.video_note | F.animation
)
async def on_non_text(msg: types.Message):
    if msg.from_user.id == ADMIN_ID:
        return
    await msg.answer(
        "🙈 Я работаю <b>только с текстом</b>.\n\n"
        "Фото, стикеры, файлы, голосовые и видео я не вижу. "
        "Опиши, что там — и я помогу."
    )


@dp.message(F.text & ~F.text.startswith("/"))
async def on_user_text(msg: types.Message):
    user = msg.from_user
    if user.id == ADMIN_ID:
        return

    now = asyncio.get_event_loop().time()
    if now - last_request.get(user.id, 0) < USER_COOLDOWN:
        await msg.answer("⏳ Слишком часто. Подожди пару секунд.")
        return

    if user.id in processing_users:
        await msg.answer("⏳ Я ещё обрабатываю предыдущий запрос. Дождись ответа.")
        return

    processing_users.add(user.id)
    last_request[user.id] = now

    try:
        await handle_ai_stream(msg, user)
    finally:
        processing_users.discard(user.id)


async def handle_ai_stream(msg: types.Message, user: types.User):
    await upsert_user(user.id, user.username, user.full_name)
    mode = await get_user_mode(user.id)

    question = sanitize_user_input(msg.text)
    await save_message(user.id, user.username, user.full_name, "user", question, mode)

    history = await get_history(user.id, max_chars=MAX_HISTORY_CHARS)

    system_prompt = build_system_prompt(user.full_name, mode)

    # Юзер видит только "Думаю…". Этот placeholder потом отредактируем в ответ.
    placeholder = await msg.answer("⏳ <i>Думаю…</i>")

    buffer = ""

    try:
        stream = await ask_ai_stream(mode, system_prompt, history, max_tokens=4000)
        async for delta in stream:
            buffer += delta
    except Exception as e:
        log.exception("AI error")
        try:
            await placeholder.edit_text(
                f"⚠️ Ошибка ИИ: <code>{type(e).__name__}</code>. Попробуй позже."
            )
        except Exception:
            pass
        return

    await save_message(user.id, user.username, user.full_name, "assistant", buffer, mode)

    # Отправляем админу, но НЕ трогаем placeholder юзера
    await send_to_admin_for_moderation(
        user, question, buffer, mode,
        user_chat_id=msg.chat.id,
        user_placeholder_id=placeholder.message_id,
    )


async def send_to_admin_for_moderation(
    user: types.User,
    question: str,
    answer: str,
    mode: str,
    user_chat_id: int,
    user_placeholder_id: int,
):
    """Отправляет админу диалог и запускает таймер авто-отправки.
    Юзер в это время видит 'Думаю…'.
    """
    header = (
        f"👤 <b>{user.full_name}</b> (@{user.username or 'без_ника'}) | "
        f"<code>{user.id}</code>\n"
        f"🎛 Режим: <b>{mode}</b>\n\n"
        f"💬 <b>Вопрос:</b>\n{question}\n\n"
        f"🤖 <b>Ответ ИИ:</b>"
    )

    try:
        sent = await bot.send_message(
            ADMIN_ID, header,
            disable_web_page_preview=True,
            reply_markup=moderation_kb(user.id),
        )
        # Ответ отдельным сообщением
        html_answer = md_to_html(answer)
        chunks = split_message(html_answer)
        answer_msg_ids = []
        for ch in chunks:
            m = await bot.send_message(ADMIN_ID, ch, disable_web_page_preview=True)
            answer_msg_ids.append(m.message_id)
    except Exception:
        log.exception("Не смог отправить админу")
        # Админ недоступен — сразу юзеру
        await auto_send_to_user(
            user_chat_id, user_placeholder_id, user.id, answer, mode
        )
        return

    task = asyncio.create_task(
        _auto_send_later(
            sent.message_id, user_chat_id, user_placeholder_id, user.id, answer, mode
        )
    )
    pending[sent.message_id] = {
        "user_id": user.id,
        "user_chat_id": user_chat_id,
        "user_placeholder_id": user_placeholder_id,
        "answer": answer,
        "mode": mode,
        "task": task,
        "header_msg_id": sent.message_id,
        "answer_msg_ids": answer_msg_ids,
    }


async def _auto_send_later(
    msg_id: int,
    user_chat_id: int,
    user_placeholder_id: int,
    user_id: int,
    answer: str,
    mode: str,
):
    try:
        await asyncio.sleep(ADMIN_TIMEOUT)
    except asyncio.CancelledError:
        return
    if msg_id not in pending:
        return
    try:
        await auto_send_to_user(user_chat_id, user_placeholder_id, user_id, answer, mode)
        try:
            await bot.send_message(
                ADMIN_ID,
                f"⏰ <i>Авто-отправлено через {ADMIN_TIMEOUT} сек "
                f"пользователю <code>{user_id}</code></i>",
            )
            await bot.edit_message_reply_markup(
                chat_id=ADMIN_ID, message_id=msg_id, reply_markup=None
            )
        except Exception:
            pass
    finally:
        pending.pop(msg_id, None)


async def auto_send_to_user(
    user_chat_id: int,
    user_placeholder_id: int,
    user_id: int,
    answer: str,
    mode: str,
):
    """Редактирует placeholder юзера в финальный красивый ответ."""
    reasoning, main = split_reasoning(answer)

    parts = []
    if reasoning:
        reasoning_html = md_to_html(reasoning)
        parts.append(
            "🧠 <b>Размышления</b>\n"
            f"<blockquote expandable>{reasoning_html}</blockquote>"
        )
    main_html = md_to_html(main)
    if parts:
        parts.append(f"💬 <b>Ответ</b>\n{main_html}")
    else:
        parts.append(main_html)

    full = "\n\n".join(parts)
    chunks = split_message(full)

    try:
        # Первый чанк — редактируем placeholder юзера
        await bot.edit_message_text(
            chat_id=user_chat_id,
            message_id=user_placeholder_id,
            text=chunks[0],
            disable_web_page_preview=True,
        )
        # Остальные чанки — новыми сообщениями
        for ch in chunks[1:]:
            await bot.send_message(
                user_chat_id, ch, disable_web_page_preview=True
            )
    except TelegramBadRequest as e:
        # Если placeholder уже нельзя редактировать — шлём новым сообщением
        log.warning(f"Не смог отредактировать placeholder: {e}")
        try:
            for ch in chunks:
                await bot.send_message(
                    user_chat_id, ch, disable_web_page_preview=True
                )
        except Exception:
            log.exception(f"Не смог отправить пользователю {user_id}")
    except Exception:
        log.exception(f"Не смог отправить пользователю {user_id}")


@dp.callback_query(F.from_user.id == ADMIN_ID, F.data.startswith("mod:"))
async def on_moderation(cb: CallbackQuery):
    _, action, user_id_str = cb.data.split(":")
    msg_id = cb.message.message_id

    entry = pending.get(msg_id)
    if not entry:
        await cb.answer("Уже обработано", show_alert=True)
        return

    entry["task"].cancel()

    if action == "send":
        await cb.message.edit_reply_markup(reply_markup=None)
        await auto_send_to_user(
            entry["user_chat_id"],
            entry["user_placeholder_id"],
            entry["user_id"],
            entry["answer"],
            entry["mode"],
        )
        await cb.answer("✅ Отправлено")
        await cb.message.reply(f"✅ Отправлено <code>{entry['user_id']}</code>")
        pending.pop(msg_id, None)

    elif action == "reject":
        await cb.message.edit_reply_markup(reply_markup=None)
        await cb.answer("❌ Отклонено")
        await cb.message.reply(f"❌ Отклонено для <code>{entry['user_id']}</code>")
        try:
            await bot.edit_message_text(
                chat_id=entry["user_chat_id"],
                message_id=entry["user_placeholder_id"],
                text="🙏 Извини, не могу ответить на этот запрос. Попробуй переформулировать.",
            )
        except Exception:
            pass
        pending.pop(msg_id, None)

    elif action == "edit":
        await cb.answer()
        await cb.message.reply(
            "✏️ Отправь новый текст <b>ответом</b> на это сообщение — "
            f"он уйдёт пользователю <code>{entry['user_id']}</code>."
        )


@dp.message(F.from_user.id == ADMIN_ID, F.reply_to_message, F.text)
async def admin_edit_reply(msg: types.Message):
    reply_id = msg.reply_to_message.message_id

    # Ищем pending: либо reply на заголовок, либо на ответ
    target_id = None
    for mid, entry in pending.items():
        if (
            mid == reply_id
            or reply_id == entry.get("header_msg_id")
            or reply_id in entry.get("answer_msg_ids", [])
        ):
            target_id = mid
            break

    if target_id is None:
        return

    entry = pending[target_id]
    entry["task"].cancel()

    await auto_send_to_user(
        entry["user_chat_id"],
        entry["user_placeholder_id"],
        entry["user_id"],
        msg.text,
        entry["mode"],
    )
    await msg.reply(
        f"✅ Отправлено пользователю <code>{entry['user_id']}</code>"
    )
    try:
        await bot.edit_message_reply_markup(
            chat_id=ADMIN_ID, message_id=target_id, reply_markup=None
        )
    except Exception:
        pass
    pending.pop(target_id, None)


@dp.message(Command("log"), F.from_user.id == ADMIN_ID)
async def cmd_log(msg: types.Message):
    import aiosqlite

    async with aiosqlite.connect(DB) as db:
        cur = await db.execute("""
            SELECT full_name, username, role, content, mode FROM messages
            ORDER BY id DESC LIMIT 30
        """)
        rows = await cur.fetchall()

    if not rows:
        await msg.answer("Пусто")
        return

    out = []
    for full_name, username, role, content, mode in reversed(rows):
        icon = "👤" if role == "user" else "🤖"
        preview = content[:200].replace("\n", " ")
        out.append(f"{icon} <b>{full_name}</b> (@{username}) [{mode}]:\n{preview}\n")

    for ch in split_message("\n".join(out)):
        await msg.answer(ch, disable_web_page_preview=True)


@dp.message(Command("users"), F.from_user.id == ADMIN_ID)
async def cmd_users(msg: types.Message):
    import aiosqlite

    async with aiosqlite.connect(DB) as db:
        cur = await db.execute(
            "SELECT user_id, username, full_name, mode FROM users "
            "ORDER BY created_at DESC"
        )
        rows = await cur.fetchall()

    if not rows:
        await msg.answer("Пока никого")
        return

    text = "\n".join(
        f"• <b>{f}</b> (@{u or '—'}) | <code>{i}</code> | {m}"
        for i, u, f, m in rows
    )
    await msg.answer(text[:4000])


async def main():
    await init_db()
    log.info("🤖 Бот запущен")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
