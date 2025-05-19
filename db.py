import aiosqlite

DB_PATH = "anon.db"


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA journal_mode=WAL;")

        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                visible BOOLEAN DEFAULT 1
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS anon_targets (
                sender_id INTEGER PRIMARY KEY,
                target_id INTEGER
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS used_txns (
                txn_id TEXT PRIMARY KEY,
                payload TEXT
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS revealed_senders (
                viewer_id INTEGER,
                sender_id INTEGER,
                PRIMARY KEY (viewer_id, sender_id)
            )
        """)

        # Проверим, есть ли колонка receiver_id в whispers
        async with db.execute("PRAGMA table_info(whispers)") as cursor:
            columns = await cursor.fetchall()
            column_names = [col[1] for col in columns]

        if "receiver_id" not in column_names:
            await db.execute("DROP TABLE IF EXISTS whispers")

        await db.execute("""
            CREATE TABLE IF NOT EXISTS whispers (
                message_id INTEGER,
                receiver_id INTEGER,
                text TEXT,
                PRIMARY KEY (message_id, receiver_id)
            )
        """)

        await db.commit()
        print("[DB] База данных успешно инициализирована")


async def register_user(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO users (user_id, visible) VALUES (?, 1)", (user_id,)
        )
        await db.commit()


async def set_user_visibility(user_id: int, visible: bool):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET visible = ? WHERE user_id = ?", (int(visible), user_id)
        )
        await db.commit()


async def is_user_visible(user_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT visible FROM users WHERE user_id = ?", (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return bool(row[0]) if row else False


async def save_target(sender_id: int, target_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO anon_targets (sender_id, target_id) VALUES (?, ?)",
            (sender_id, target_id)
        )
        await db.commit()


async def get_target_id(sender_id: int) -> int | None:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT target_id FROM anon_targets WHERE sender_id = ?", (sender_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else None


async def save_txn_id(txn_id: str, payload: str = "") -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        try:
            await db.execute(
                "INSERT INTO used_txns (txn_id, payload) VALUES (?, ?)", (txn_id, payload)
            )
            await db.commit()
            return True
        except aiosqlite.IntegrityError:
            return False


async def check_sender_revealed(viewer_id: int, sender_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("""
            SELECT 1 FROM revealed_senders
            WHERE viewer_id = ? AND sender_id = ?
        """, (viewer_id, sender_id)) as cursor:
            return await cursor.fetchone() is not None


async def mark_sender_revealed(viewer_id: int, sender_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT OR IGNORE INTO revealed_senders (viewer_id, sender_id)
            VALUES (?, ?)
        """, (viewer_id, sender_id))
        await db.commit()


async def save_whisper(message_id: int, receiver_id: int, text: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT OR REPLACE INTO whispers (message_id, receiver_id, text)
            VALUES (?, ?, ?)
        """, (message_id, receiver_id, text))
        await db.commit()


async def get_and_delete_whisper(message_id: int, receiver_id: int) -> str | None:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("""
            SELECT text FROM whispers
            WHERE message_id = ? AND receiver_id = ?
        """, (message_id, receiver_id)) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None
        await db.execute("""
            DELETE FROM whispers
            WHERE message_id = ? AND receiver_id = ?
        """, (message_id, receiver_id))
        await db.commit()
        return row[0]


async def get_whisper_text(message_id: int, receiver_id: int) -> str | None:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("""
            SELECT text FROM whispers
            WHERE message_id = ? AND receiver_id = ?
        """, (message_id, receiver_id)) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else None
