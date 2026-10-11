import os
import aiosqlite
from config import DB_PATH

DB = DB_PATH


async def init_db():
    db_dir = os.path.dirname(DB)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)

    async with aiosqlite.connect(DB) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                username TEXT,
                full_name TEXT,
                role TEXT,
                content TEXT,
                mode TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                full_name TEXT,
                mode TEXT DEFAULT 'chat',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_messages_user ON messages(user_id)"
        )
        await db.commit()


async def upsert_user(user_id, username, full_name):
    async with aiosqlite.connect(DB) as db:
        await db.execute("""
            INSERT INTO users (user_id, username, full_name) VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                username=excluded.username,
                full_name=excluded.full_name
        """, (user_id, username, full_name))
        await db.commit()


async def save_message(user_id, username, full_name, role, content, mode):
    async with aiosqlite.connect(DB) as db:
        await db.execute(
            "INSERT INTO messages (user_id, username, full_name, role, content, mode) "
            "VALUES (?,?,?,?,?,?)",
            (user_id, username, full_name, role, content, mode)
        )
        await db.commit()


async def get_history(user_id, max_chars=12000):
    async with aiosqlite.connect(DB) as db:
        cur = await db.execute("""
            SELECT role, content FROM messages
            WHERE user_id = ? ORDER BY id DESC LIMIT 40
        """, (user_id,))
        rows = await cur.fetchall()

    history, total = [], 0
    for role, content in rows:
        if total + len(content) > max_chars:
            break
        history.append({"role": role, "content": content})
        total += len(content)
    return list(reversed(history))


async def get_user_mode(user_id):
    async with aiosqlite.connect(DB) as db:
        cur = await db.execute("SELECT mode FROM users WHERE user_id = ?", (user_id,))
        row = await cur.fetchone()
        return row[0] if row else "chat"


async def set_user_mode(user_id, mode):
    async with aiosqlite.connect(DB) as db:
        await db.execute("UPDATE users SET mode = ? WHERE user_id = ?", (mode, user_id))
        await db.commit()


async def clear_history(user_id):
    async with aiosqlite.connect(DB) as db:
        await db.execute("DELETE FROM messages WHERE user_id = ?", (user_id,))
        await db.commit()
