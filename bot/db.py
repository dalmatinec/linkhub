"""База SQLite: чаты, юзеры, история сообщений, фразы, реклама, расход на ИИ."""

import json
import time
from datetime import datetime, timedelta

import aiosqlite

from bot import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS chats (
    chat_id     INTEGER PRIMARY KEY,
    title       TEXT    NOT NULL DEFAULT '',
    active      INTEGER NOT NULL DEFAULT 1,
    bot_name    TEXT    NOT NULL,
    aliases     TEXT    NOT NULL DEFAULT '',
    persona     TEXT    NOT NULL,
    topic       TEXT    NOT NULL,
    chance      REAL    NOT NULL,
    ai_share    REAL    NOT NULL,
    cooldown    INTEGER NOT NULL,
    greet       INTEGER NOT NULL DEFAULT 1,
    games       INTEGER NOT NULL DEFAULT 1,
    ads         INTEGER NOT NULL DEFAULT 1,
    last_jump   REAL    NOT NULL DEFAULT 0,
    created_at  REAL    NOT NULL
);

CREATE TABLE IF NOT EXISTS users (
    chat_id     INTEGER NOT NULL,
    user_id     INTEGER NOT NULL,
    name        TEXT    NOT NULL DEFAULT '',
    username    TEXT    NOT NULL DEFAULT '',
    msg_count   INTEGER NOT NULL DEFAULT 0,
    last_seen   REAL    NOT NULL DEFAULT 0,
    notes       TEXT    NOT NULL DEFAULT '',
    notes_at    INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (chat_id, user_id)
);

CREATE TABLE IF NOT EXISTS history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id     INTEGER NOT NULL,
    message_id  INTEGER NOT NULL,
    user_id     INTEGER NOT NULL,
    name        TEXT    NOT NULL,
    text        TEXT    NOT NULL,
    reply_name  TEXT    NOT NULL DEFAULT '',
    is_bot      INTEGER NOT NULL DEFAULT 0,
    ts          REAL    NOT NULL
);
CREATE INDEX IF NOT EXISTS history_chat ON history (chat_id, id);
CREATE INDEX IF NOT EXISTS history_msg ON history (chat_id, message_id);
CREATE INDEX IF NOT EXISTS history_ts ON history (chat_id, ts);

CREATE TABLE IF NOT EXISTS phrases (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    kind        TEXT    NOT NULL,          -- text | sticker | gif
    content     TEXT    NOT NULL,          -- текст или file_id
    created_at  REAL    NOT NULL,
    UNIQUE (kind, content)
);

CREATE TABLE IF NOT EXISTS ads (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    title       TEXT    NOT NULL,
    media_kind  TEXT    NOT NULL DEFAULT '',   -- '' | photo | video | gif
    file_id     TEXT    NOT NULL DEFAULT '',
    text_html   TEXT    NOT NULL DEFAULT '',
    buttons     TEXT    NOT NULL DEFAULT '[]', -- [[["текст","ссылка"], ...], ...]
    interval    INTEGER NOT NULL DEFAULT 180,  -- минуты
    enabled     INTEGER NOT NULL DEFAULT 1,
    delete_prev INTEGER NOT NULL DEFAULT 1,
    created_at  REAL    NOT NULL
);

CREATE TABLE IF NOT EXISTS ad_sends (
    ad_id       INTEGER NOT NULL,
    chat_id     INTEGER NOT NULL,
    last_sent   REAL    NOT NULL,
    message_id  INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (ad_id, chat_id)
);

CREATE TABLE IF NOT EXISTS spend (
    day         TEXT    PRIMARY KEY,
    usd         REAL    NOT NULL DEFAULT 0,
    requests    INTEGER NOT NULL DEFAULT 0,
    tok_in      INTEGER NOT NULL DEFAULT 0,
    tok_out     INTEGER NOT NULL DEFAULT 0
);

-- разбивка расхода нейросети: по часам (время бота), чатам и видам запросов
CREATE TABLE IF NOT EXISTS ai_log (
    day         TEXT    NOT NULL,
    hour        INTEGER NOT NULL,
    chat_id     INTEGER NOT NULL,
    kind        TEXT    NOT NULL,
    requests    INTEGER NOT NULL DEFAULT 0,
    usd         REAL    NOT NULL DEFAULT 0,
    PRIMARY KEY (day, hour, chat_id, kind)
);

CREATE TABLE IF NOT EXISTS couples (
    chat_id     INTEGER NOT NULL,
    day         TEXT    NOT NULL,
    user1       INTEGER NOT NULL,
    user2       INTEGER NOT NULL,
    PRIMARY KEY (chat_id, day)
);

CREATE TABLE IF NOT EXISTS daily_stats (
    chat_id     INTEGER NOT NULL,
    day         TEXT    NOT NULL,
    user_id     INTEGER NOT NULL,
    name        TEXT    NOT NULL DEFAULT '',
    msgs        INTEGER NOT NULL DEFAULT 0,
    mat         INTEGER NOT NULL DEFAULT 0,   -- сообщений с матом
    laughs      INTEGER NOT NULL DEFAULT 0,   -- сколько раз над ним поржали в ответах
    PRIMARY KEY (chat_id, day, user_id)
);

CREATE TABLE IF NOT EXISTS msg_reacts (
    chat_id     INTEGER NOT NULL,
    message_id  INTEGER NOT NULL,
    user_id     INTEGER NOT NULL,             -- автор сообщения
    name        TEXT    NOT NULL,
    text        TEXT    NOT NULL,
    ts          REAL    NOT NULL,             -- когда написано сообщение
    total       INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (chat_id, message_id)
);

CREATE TABLE IF NOT EXISTS pair_polls (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id     INTEGER NOT NULL,
    user1       INTEGER NOT NULL,
    user2       INTEGER NOT NULL,
    name1       TEXT    NOT NULL,
    name2       TEXT    NOT NULL,
    message_id  INTEGER NOT NULL DEFAULT 0,
    created     REAL    NOT NULL,
    closed      INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS pair_votes (
    poll_id     INTEGER NOT NULL,
    user_id     INTEGER NOT NULL,
    vote        INTEGER NOT NULL,             -- 1 огонь, 0 не верю
    PRIMARY KEY (poll_id, user_id)
);

CREATE TABLE IF NOT EXISTS rep_points (
    chat_id     INTEGER NOT NULL,
    user_id     INTEGER NOT NULL,
    points      INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (chat_id, user_id)
);

CREATE TABLE IF NOT EXISTS rep_log (
    chat_id     INTEGER NOT NULL,
    giver       INTEGER NOT NULL,
    receiver    INTEGER NOT NULL,
    ts          REAL    NOT NULL
);
CREATE INDEX IF NOT EXISTS rep_log_giver ON rep_log (chat_id, giver, ts);

CREATE TABLE IF NOT EXISTS screens (
    key         TEXT    PRIMARY KEY,
    text_html   TEXT    NOT NULL,
    photo       TEXT    NOT NULL DEFAULT '',
    buttons     TEXT    NOT NULL DEFAULT '[]'  -- [{"text","action","style","emoji","row"}]
);

CREATE TABLE IF NOT EXISTS ad_products (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    kind        TEXT    NOT NULL,               -- groups | pin_groups | pin_channel | dm
    title       TEXT    NOT NULL,
    price       REAL    NOT NULL,               -- USDT
    days        INTEGER NOT NULL DEFAULT 1,     -- для groups: сколько дней подряд по посту
    enabled     INTEGER NOT NULL DEFAULT 1,
    sort        INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS orders (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL,
    user_name   TEXT    NOT NULL DEFAULT '',
    kind        TEXT    NOT NULL,               -- как в ad_products, плюс both (рассылка везде)
    title       TEXT    NOT NULL,
    price       REAL    NOT NULL DEFAULT 0,
    days        INTEGER NOT NULL DEFAULT 1,
    media_kind  TEXT    NOT NULL DEFAULT '',
    file_id     TEXT    NOT NULL DEFAULT '',
    text_html   TEXT    NOT NULL DEFAULT '',
    buttons     TEXT    NOT NULL DEFAULT '[]',
    status      TEXT    NOT NULL,               -- moderation, awaiting, paid, running, done, rejected, expired
    amount      INTEGER NOT NULL DEFAULT 0,     -- точная сумма к оплате в микро-USDT (6 знаков)
    tx          TEXT    NOT NULL DEFAULT '',
    created     REAL    NOT NULL,
    paid_at     REAL    NOT NULL DEFAULT 0,
    next_run    REAL    NOT NULL DEFAULT 0,
    runs_left   INTEGER NOT NULL DEFAULT 0,
    result      TEXT    NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS pins (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id     INTEGER NOT NULL,
    message_id  INTEGER NOT NULL,
    unpin_at    REAL    NOT NULL
);

CREATE TABLE IF NOT EXISTS ton_seen (
    tx          TEXT    PRIMARY KEY,            -- уже учтённые входящие переводы
    ts          REAL    NOT NULL
);

CREATE TABLE IF NOT EXISTS shop_items (
    key         TEXT    PRIMARY KEY,           -- don20, don100, title, shield, roast_full
    title       TEXT    NOT NULL,
    stars       INTEGER NOT NULL,
    enabled     INTEGER NOT NULL DEFAULT 1,
    sort        INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS star_payments (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL,
    name        TEXT    NOT NULL DEFAULT '',
    item        TEXT    NOT NULL,
    stars       INTEGER NOT NULL,
    charge_id   TEXT    NOT NULL,
    payload     TEXT    NOT NULL DEFAULT '',
    ts          REAL    NOT NULL,
    refunded    INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS perks (
    user_id     INTEGER PRIMARY KEY,
    title       TEXT    NOT NULL DEFAULT '',
    title_until REAL    NOT NULL DEFAULT 0,
    shield_until REAL   NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS chat_titles (
    chat_id     INTEGER NOT NULL,
    user_id     INTEGER NOT NULL,
    title       TEXT    NOT NULL,
    until       REAL    NOT NULL,                -- когда снять должность
    PRIMARY KEY (chat_id, user_id)
);

CREATE TABLE IF NOT EXISTS dm_users (
    user_id     INTEGER PRIMARY KEY,
    name        TEXT    NOT NULL DEFAULT '',
    username    TEXT    NOT NULL DEFAULT '',
    started     REAL    NOT NULL,
    last_seen   REAL    NOT NULL,
    blocked     INTEGER NOT NULL DEFAULT 0       -- заблокировал бота: рассылки ему не шлём
);

CREATE TABLE IF NOT EXISTS triggers (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id     INTEGER NOT NULL,
    word        TEXT    NOT NULL,               -- слово или фраза, в нижнем регистре
    media_kind  TEXT    NOT NULL DEFAULT '',    -- '' | photo | video | gif | sticker
    file_id     TEXT    NOT NULL DEFAULT '',
    text_html   TEXT    NOT NULL DEFAULT '',
    created     REAL    NOT NULL
);
CREATE INDEX IF NOT EXISTS triggers_chat ON triggers (chat_id);

CREATE TABLE IF NOT EXISTS support_threads (
    user_id     INTEGER PRIMARY KEY,
    name        TEXT    NOT NULL DEFAULT '',
    username    TEXT    NOT NULL DEFAULT '',
    topic       TEXT    NOT NULL DEFAULT '',
    status      TEXT    NOT NULL DEFAULT 'new', -- new | answered | closed
    last_ts     REAL    NOT NULL
);

CREATE TABLE IF NOT EXISTS support_msgs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL,
    direction   TEXT    NOT NULL,               -- in: от человека, out: ответ владельца
    text        TEXT    NOT NULL DEFAULT '',
    ts          REAL    NOT NULL
);
CREATE INDEX IF NOT EXISTS support_msgs_user ON support_msgs (user_id, id);

CREATE TABLE IF NOT EXISTS emoji_pack (
    emoji_id    TEXT    PRIMARY KEY,            -- id премиум-эмодзи
    alt         TEXT    NOT NULL                -- обычный эмодзи, вместо которого он показывается
);

CREATE TABLE IF NOT EXISTS call_list (
    chat_id     INTEGER NOT NULL,
    user_id     INTEGER NOT NULL,
    name        TEXT    NOT NULL DEFAULT '',
    PRIMARY KEY (chat_id, user_id)
);

CREATE TABLE IF NOT EXISTS kv (
    key         TEXT    PRIMARY KEY,            -- служебные настройки: канал бэкапов и т.п.
    value       TEXT    NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS quiz_scores (
    chat_id     INTEGER NOT NULL,
    user_id     INTEGER NOT NULL,
    points      INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (chat_id, user_id)
);
"""

# Колонки, которых не было в первой версии. Добавляются в старую базу при запуске.
NEW_COLUMNS = {
    "chats": {
        "pairpoll": "INTEGER NOT NULL DEFAULT 1",       # «как вам пара»
        "results": "INTEGER NOT NULL DEFAULT 1",        # итоги дня
        "rep": "INTEGER NOT NULL DEFAULT 1",            # репутация
        "bday": "INTEGER NOT NULL DEFAULT 1",           # поздравления с ДР
        "results_hour": "INTEGER NOT NULL DEFAULT 23",
        "card_style": "INTEGER NOT NULL DEFAULT -1",     # цвет карточек итогов (-1: свой по номеру чата)
        "act_locked": "INTEGER NOT NULL DEFAULT 0",
        "share_notes": "INTEGER NOT NULL DEFAULT 1",     # общая память: бот узнаёт людей по заметкам из других чатов      # владелец закрепил частоту, долю ИИ и паузу: админ чата не меняет
        "last_results": "TEXT NOT NULL DEFAULT ''",
        "last_pairpoll": "TEXT NOT NULL DEFAULT ''",
        "results_manual": "REAL NOT NULL DEFAULT 0",      # когда последний раз звали «итоги»
        # у старых чатов при обновлении approved = 1, новые чаты добавляются с approved = 0
        "approved": "INTEGER NOT NULL DEFAULT 1",
        "pending_since": "REAL NOT NULL DEFAULT 0",       # когда ушла заявка на одобрение
        "added_by": "INTEGER NOT NULL DEFAULT 0",
        "rent_until": "REAL NOT NULL DEFAULT 0",          # 0 = без срока
        "rent_warned": "INTEGER NOT NULL DEFAULT 0",
        "members": "INTEGER NOT NULL DEFAULT 0",          # участников, обновляется раз в сутки
        "shop": "INTEGER NOT NULL DEFAULT 1",             # монеты, питомцы, кости и магазин за монеты
        "added_name": "TEXT NOT NULL DEFAULT ''",         # кто добавил бота: имя
        "added_username": "TEXT NOT NULL DEFAULT ''",     # и юзернейм, чтобы владелец мог связаться
        "quiz": "INTEGER NOT NULL DEFAULT 1",             # викторины включены
        "quiz_count": "INTEGER NOT NULL DEFAULT 5",       # вопросов в викторине
        "quiet_from": "INTEGER NOT NULL DEFAULT -1",      # тихие часы: с какого часа (-1 выкл)
        "quiet_to": "INTEGER NOT NULL DEFAULT -1",
        "quiet_until": "REAL NOT NULL DEFAULT 0",         # «помолчи часок»: до какого времени молчать
        "humor": "INTEGER NOT NULL DEFAULT 1",            # 0 мягко, 1 обычно, 2 дерзко
        "mat": "INTEGER NOT NULL DEFAULT 1",              # 0 нельзя, 1 в меру, 2 можно
        "banned": "TEXT NOT NULL DEFAULT ''",             # запретные темы
        "protect_admins": "INTEGER NOT NULL DEFAULT 0",   # админов нельзя прожаривать
        "call_text": "TEXT NOT NULL DEFAULT ''",          # зазывала: текст (HTML)
        "call_who": "TEXT NOT NULL DEFAULT 'day'",        # hour | day | week | all | list
        "call_style": "TEXT NOT NULL DEFAULT 'names'",    # names: имена, emoji: отметки спрятаны в эмодзи
        "call_max": "INTEGER NOT NULL DEFAULT 50",
        "trial": "INTEGER NOT NULL DEFAULT 0",            # сейчас идёт пробный период
        "qday": "INTEGER NOT NULL DEFAULT 1",             # вопрос дня включён
        "last_qday": "TEXT NOT NULL DEFAULT ''",          # когда последний раз задавали
        "qday_queue": "TEXT NOT NULL DEFAULT ''",         # свои вопросы дня от админа, по строке
        "revive": "INTEGER NOT NULL DEFAULT 0",           # через сколько минут тишины оживлять чат (0 выкл)
        "last_revive": "REAL NOT NULL DEFAULT 0",
        "free": "INTEGER NOT NULL DEFAULT 0",             # бесплатный тариф: без нейросети
        "trial_used": "INTEGER NOT NULL DEFAULT 0",       # пробный уже был
        "last_nudge": "REAL NOT NULL DEFAULT 0",          # когда напоминали про платную версию
        "guard_tease": "INTEGER NOT NULL DEFAULT 0",      # подкалывать тех, кого наказал модератор
    },
    "users": {
        "birthday": "TEXT NOT NULL DEFAULT ''",         # 'MM-DD'
        "bday_year": "INTEGER NOT NULL DEFAULT 0",      # в каком году уже поздравили
        "first_seen": "REAL NOT NULL DEFAULT 0",        # когда впервые увидели в чате (вход или первое сообщение)
    },
    "history": {
        "reply_user_id": "INTEGER NOT NULL DEFAULT 0",
    },
    "orders": {
        "target": "INTEGER NOT NULL DEFAULT 0",          # для аренды: id чата
    },
    "perks": {
        "vip_until": "REAL NOT NULL DEFAULT 0",
        "emoji_id": "TEXT NOT NULL DEFAULT ''",          # премиум-эмодзи VIP у имени
        "emoji_alt": "TEXT NOT NULL DEFAULT ''",         # обычный эмодзи, если премиум не показывается
        "nick": "TEXT NOT NULL DEFAULT ''",              # ник VIP вместо имени
        "look_forever": "INTEGER NOT NULL DEFAULT 0",    # ник и эмодзи куплены за монеты навсегда
    },
}

CHAT_FIELDS = {"bot_name", "aliases", "persona", "topic", "chance", "ai_share",
               "cooldown", "greet", "games", "ads", "title", "active", "last_jump",
               "pairpoll", "results", "rep", "bday", "results_hour", "last_results", "last_pairpoll", "card_style", "act_locked", "share_notes",
               "results_manual", "approved", "pending_since", "added_by", "rent_until", "rent_warned", "members",
               "shop", "added_name", "added_username", "quiz", "quiz_count", "quiet_from", "quiet_to",
               "quiet_until", "humor", "mat", "banned", "protect_admins", "call_text", "call_who", "call_style",
               "call_max", "trial", "qday", "last_qday", "qday_queue", "revive", "last_revive", "free", "trial_used", "last_nudge",
               "guard_tease"}
AD_FIELDS = {"title", "media_kind", "file_id", "text_html", "buttons", "interval",
             "enabled", "delete_prev"}

_db: aiosqlite.Connection | None = None


def today() -> str:
    return datetime.now(config.TZ).strftime("%Y-%m-%d")


def _swap_restored() -> None:
    """Если владелец восстановил базу из бэкапа через бота, подменяем её до подключения."""
    restored = config.DATA_DIR / "restore.db"
    if not restored.exists():
        return
    import shutil
    if config.DB_PATH.exists():
        shutil.copy2(config.DB_PATH, config.DATA_DIR / f"bot.db.before-restore-{int(time.time())}")
    for ext in ("-wal", "-shm"):
        side = config.DB_PATH.with_name(config.DB_PATH.name + ext)
        if side.exists():
            side.unlink()
    restored.replace(config.DB_PATH)


async def connect() -> None:
    global _db
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    _swap_restored()
    _db = await aiosqlite.connect(config.DB_PATH)
    _db.row_factory = aiosqlite.Row
    await _db.execute("PRAGMA journal_mode=WAL")
    await _db.execute("PRAGMA synchronous=NORMAL")
    await _db.executescript(SCHEMA)
    await _migrate()
    await _db.commit()
    await _seed_phrases()


async def _migrate() -> None:
    for table, columns in NEW_COLUMNS.items():
        async with conn().execute(f"PRAGMA table_info({table})") as cur:
            have = {row[1] for row in await cur.fetchall()}
        for name, ddl in columns.items():
            if name not in have:
                await conn().execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")
                if (table, name) == ("users", "first_seen"):  # старым людям: самое раннее сообщение из истории
                    await conn().execute(
                        "UPDATE users SET first_seen = COALESCE((SELECT MIN(h.ts) FROM history h WHERE "
                        "h.chat_id = users.chat_id AND h.user_id = users.user_id), 0)")


async def close() -> None:
    if _db is not None:
        await _db.close()


def conn() -> aiosqlite.Connection:
    assert _db is not None, "база не открыта"
    return _db


def phrase_kind(cat: str) -> str:
    """Категория фраз → значение kind в базе. Обычные фразы исторически лежат как 'text'."""
    return "text" if cat == "any" else cat


async def _seed_phrases() -> None:
    """Добавляет стартовые фразы новой версии (повторы пропускаются)."""
    from bot.phrases_seed import PHRASES, SEED_VERSION
    async with conn().execute("SELECT value FROM kv WHERE key = 'seed_version'") as cur:
        row = await cur.fetchone()
    if row and int(row[0] or 0) >= SEED_VERSION:
        return
    now = time.time()
    await conn().executemany("INSERT OR IGNORE INTO phrases (kind, content, created_at) VALUES (?, ?, ?)",
                             [(phrase_kind(cat), p, now) for cat, items in PHRASES.items() for p in items])
    await conn().execute("INSERT OR REPLACE INTO kv (key, value) VALUES ('seed_version', ?)", (str(SEED_VERSION),))
    await conn().commit()


# ---------- чаты ----------

async def ensure_chat(chat_id: int, title: str) -> aiosqlite.Row:
    """Новый чат появляется неодобренным: бот в нём молчит, пока владелец не разрешит."""
    await conn().execute(
        """INSERT INTO chats (chat_id, title, bot_name, persona, topic, chance, ai_share, cooldown, created_at,
                              approved)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
           ON CONFLICT(chat_id) DO UPDATE SET title = excluded.title, active = 1""",
        (chat_id, title, config.DEFAULT_NAME or "бот", config.DEFAULT_PERSONA, config.DEFAULT_TOPIC,
         config.DEFAULT_CHANCE, config.DEFAULT_AI_SHARE, config.DEFAULT_COOLDOWN, time.time()))
    await conn().commit()
    return await get_chat(chat_id)


async def fix_legacy_name(new_name: str) -> int:
    """Чаты, где бот так и остался «Маратом» по умолчанию, переименовать в имя из профиля бота
    и стереть заметки, где это имя могло прилипнуть к людям. Возвращает, сколько чатов поправлено."""
    async with conn().execute("SELECT chat_id FROM chats WHERE bot_name = ?", (config.LEGACY_NAME,)) as cur:
        ids = [r[0] for r in await cur.fetchall()]
    for chat_id in ids:
        await conn().execute("UPDATE chats SET bot_name = ? WHERE chat_id = ?", (new_name, chat_id))
        await conn().execute("UPDATE users SET notes = '', notes_at = 0 WHERE chat_id = ? AND notes LIKE ?",
                             (chat_id, f"%{config.LEGACY_NAME}%"))
        await conn().execute("UPDATE history SET name = ? WHERE chat_id = ? AND is_bot = 1", (new_name, chat_id))
        await conn().execute("UPDATE history SET reply_name = ? WHERE chat_id = ? AND reply_name = ?",
                             (new_name, chat_id, config.LEGACY_NAME))
    await conn().commit()
    return len(ids)


async def candidate_chats(user_id: int, approved_only: bool = True) -> list[aiosqlite.Row]:
    """Рабочие чаты, где человек мог бы быть админом: он туда писал или сам добавил бота.
    Права всё равно проверяются у Telegram, это только чтобы не опрашивать все чаты подряд."""
    ok = "AND approved = 1 " if approved_only else ""
    async with conn().execute(
            "SELECT * FROM chats WHERE active = 1 " + ok + "AND (added_by = ? OR chat_id IN "
            "(SELECT chat_id FROM users WHERE user_id = ?)) ORDER BY title", (user_id, user_id)) as cur:
        return list(await cur.fetchall())


async def pending_chats() -> list[aiosqlite.Row]:
    async with conn().execute("SELECT * FROM chats WHERE active = 1 AND approved = 0 AND pending_since > 0") as cur:
        return list(await cur.fetchall())


async def get_chat(chat_id: int) -> aiosqlite.Row | None:
    async with conn().execute("SELECT * FROM chats WHERE chat_id = ?", (chat_id,)) as cur:
        return await cur.fetchone()


async def list_chats(active_only: bool = True) -> list[aiosqlite.Row]:
    """active_only: только чаты, где бот есть и его одобрили. Иначе все, включая заявки."""
    sql = "SELECT * FROM chats" + (" WHERE active = 1 AND approved = 1" if active_only else "") + " ORDER BY title"
    async with conn().execute(sql) as cur:
        return list(await cur.fetchall())


async def update_chat(chat_id: int, **fields) -> None:
    bad = set(fields) - CHAT_FIELDS
    if bad:
        raise ValueError(f"неизвестные поля чата: {bad}")
    sets = ", ".join(f"{k} = ?" for k in fields)
    await conn().execute(f"UPDATE chats SET {sets} WHERE chat_id = ?", (*fields.values(), chat_id))
    await conn().commit()


async def migrate_chat(old_id: int, new_id: int) -> None:
    """Группа стала супергруппой: у неё новый ID. Строку нового ID, если успела появиться, заменяем старой."""
    if await get_chat(old_id):
        await conn().execute("DELETE FROM chats WHERE chat_id = ?", (new_id,))
    for table in ("chats", "users", "history", "ad_sends", "couples", "daily_stats", "msg_reacts",
                  "pair_polls", "rep_points", "rep_log", "quiz_scores"):
        await conn().execute(f"UPDATE OR IGNORE {table} SET chat_id = ? WHERE chat_id = ?", (new_id, old_id))
    await conn().commit()


# ---------- юзеры ----------

async def touch_user(chat_id: int, user_id: int, name: str, username: str) -> aiosqlite.Row:
    await conn().execute(
        """INSERT INTO users (chat_id, user_id, name, username, msg_count, last_seen, first_seen)
           VALUES (?, ?, ?, ?, 1, ?, ?)
           ON CONFLICT(chat_id, user_id) DO UPDATE SET
               name = excluded.name, username = excluded.username,
               msg_count = msg_count + 1, last_seen = excluded.last_seen""",
        (chat_id, user_id, name, username, time.time(), time.time()))
    await conn().commit()
    return await get_user(chat_id, user_id)


async def add_user_silently(chat_id: int, user_id: int, name: str, username: str) -> None:
    """Новичок вступил: запоминаем, но сообщений у него ещё нет."""
    await conn().execute(
        """INSERT INTO users (chat_id, user_id, name, username, last_seen, first_seen) VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT(chat_id, user_id) DO UPDATE SET name = excluded.name, username = excluded.username,
               first_seen = CASE WHEN first_seen = 0 THEN excluded.first_seen ELSE first_seen END""",
        (chat_id, user_id, name, username, time.time(), time.time()))
    await conn().commit()


async def get_user(chat_id: int, user_id: int) -> aiosqlite.Row | None:
    async with conn().execute("SELECT * FROM users WHERE chat_id = ? AND user_id = ?",
                              (chat_id, user_id)) as cur:
        return await cur.fetchone()


async def users_by_ids(chat_id: int, ids: list[int]) -> list[aiosqlite.Row]:
    if not ids:
        return []
    marks = ",".join("?" * len(ids))
    async with conn().execute(f"SELECT * FROM users WHERE chat_id = ? AND user_id IN ({marks})",
                              (chat_id, *ids)) as cur:
        return list(await cur.fetchall())


async def active_users(chat_id: int, days: int = 7, limit: int = 300) -> list[aiosqlite.Row]:
    """Те, кто писал за последние дни. Только из них берутся рандомы в играх."""
    since = time.time() - days * 86400
    async with conn().execute(
            "SELECT * FROM users WHERE chat_id = ? AND last_seen >= ? AND msg_count > 0 "
            "ORDER BY last_seen DESC LIMIT ?", (chat_id, since, limit)) as cur:
        return list(await cur.fetchall())


async def set_notes(chat_id: int, user_id: int, notes: str, at_count: int) -> None:
    await conn().execute("UPDATE users SET notes = ?, notes_at = ? WHERE chat_id = ? AND user_id = ?",
                         (notes, at_count, chat_id, user_id))
    await conn().commit()


# ---------- история ----------

async def add_history(chat_id: int, message_id: int, user_id: int, name: str, text: str,
                      reply_name: str = "", is_bot: bool = False, reply_user_id: int = 0) -> None:
    await conn().execute(
        "INSERT INTO history (chat_id, message_id, user_id, name, text, reply_name, is_bot, ts, reply_user_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (chat_id, message_id, user_id, name, text[:1000], reply_name, int(is_bot), time.time(), reply_user_id))
    # держим в базе только последние HISTORY_KEEP сообщений чата
    await conn().execute(
        "DELETE FROM history WHERE chat_id = ? AND id <= "
        "(SELECT id FROM history WHERE chat_id = ? ORDER BY id DESC LIMIT 1 OFFSET ?)",
        (chat_id, chat_id, config.HISTORY_KEEP))
    await conn().commit()


async def recent_history(chat_id: int, limit: int) -> list[aiosqlite.Row]:
    async with conn().execute(
            "SELECT * FROM history WHERE chat_id = ? ORDER BY id DESC LIMIT ?", (chat_id, limit)) as cur:
        rows = list(await cur.fetchall())
    rows.reverse()
    return rows


async def user_messages(chat_id: int, user_id: int, limit: int) -> list[str]:
    """Последние сообщения человека; если он кому-то отвечал, с пометкой (отвечает X)."""
    async with conn().execute(
            "SELECT text, reply_name FROM history WHERE chat_id = ? AND user_id = ? ORDER BY id DESC LIMIT ?",
            (chat_id, user_id, limit)) as cur:
        rows = await cur.fetchall()
    return [(f"(отвечает {r['reply_name']}) " if r["reply_name"] else "") + r["text"] for r in reversed(rows)]


async def notes_of(user_id: int) -> list[aiosqlite.Row]:
    """Заметки бота о человеке во всех чатах."""
    async with conn().execute(
            "SELECT u.chat_id, u.notes, COALESCE(c.title, '') AS title FROM users u LEFT JOIN chats c "
            "ON c.chat_id = u.chat_id WHERE u.user_id = ? AND u.notes != ''", (user_id,)) as cur:
        return list(await cur.fetchall())


async def notes_elsewhere(chat_id: int, ids: list[int]) -> dict[int, str]:
    """Заметки о людях из других чатов (где общая память не выключена). Если человек есть в нескольких,
    берём чат, где он больше всего писал: там бот знает его лучше."""
    if not ids:
        return {}
    marks = ",".join("?" * len(ids))
    async with conn().execute(
            f"SELECT u.user_id, u.notes FROM users u LEFT JOIN chats c ON c.chat_id = u.chat_id "
            f"WHERE u.user_id IN ({marks}) AND u.chat_id != ? AND u.notes != '' AND COALESCE(c.share_notes, 1) = 1 "
            f"ORDER BY u.msg_count ASC", (*ids, chat_id)) as cur:
        return {r["user_id"]: r["notes"] for r in await cur.fetchall()}   # последний (самый активный) перезаписывает


async def clear_notes(chat_id: int | None = None, user_id: int | None = None) -> int:
    """Стереть заметки: одного человека, всего чата или (без аргументов) все. Бот заново узнает людей."""
    where, args = ["notes != ''"], []
    if chat_id is not None:
        where.append("chat_id = ?")
        args.append(chat_id)
    if user_id is not None:
        where.append("user_id = ?")
        args.append(user_id)
    # notes_at = msg_count: новая заметка появится через MEMORY_FIRST сообщений человека после очистки
    cur = await conn().execute("UPDATE users SET notes = '', notes_at = msg_count WHERE " + " AND ".join(where), args)
    await conn().commit()
    return cur.rowcount


async def clear_memory(chat_id: int) -> None:
    await conn().execute("DELETE FROM history WHERE chat_id = ?", (chat_id,))
    await conn().execute("UPDATE users SET notes = '', notes_at = 0 WHERE chat_id = ?", (chat_id,))
    await conn().commit()


KEEP_ON_DELETE = {"orders", "star_payments"}  # деньги и заказы не трогаем даже у удалённых чатов


async def delete_chat(chat_id: int) -> None:
    """Полностью убрать чат из базы: настройки, людей, историю, статистику. Платежи остаются."""
    async with conn().execute("SELECT name FROM sqlite_master WHERE type = 'table'") as cur:
        tables = [r[0] for r in await cur.fetchall()]
    for table in tables:
        if table in KEEP_ON_DELETE:
            continue
        async with conn().execute(f"PRAGMA table_info({table})") as cur:
            cols = {r[1] for r in await cur.fetchall()}
        if "chat_id" in cols:
            await conn().execute(f"DELETE FROM {table} WHERE chat_id = ?", (chat_id,))
    await conn().commit()


async def inactive_chats() -> list[aiosqlite.Row]:
    async with conn().execute("SELECT * FROM chats WHERE active = 0 ORDER BY title") as cur:
        return list(await cur.fetchall())


# ---------- фразы, стикеры, гифки ----------

async def add_phrase(kind: str, content: str) -> bool:
    cur = await conn().execute("INSERT OR IGNORE INTO phrases (kind, content, created_at) VALUES (?, ?, ?)",
                               (kind, content, time.time()))
    await conn().commit()
    return cur.rowcount > 0


async def random_phrase(kind: str) -> str | None:
    async with conn().execute("SELECT content FROM phrases WHERE kind = ? ORDER BY RANDOM() LIMIT 1",
                              (kind,)) as cur:
        row = await cur.fetchone()
    return row["content"] if row else None


async def list_phrases(kind: str, offset: int, limit: int) -> tuple[list[aiosqlite.Row], int]:
    async with conn().execute("SELECT COUNT(*) FROM phrases WHERE kind = ?", (kind,)) as cur:
        total = (await cur.fetchone())[0]
    async with conn().execute("SELECT * FROM phrases WHERE kind = ? ORDER BY id DESC LIMIT ? OFFSET ?",
                              (kind, limit, offset)) as cur:
        return list(await cur.fetchall()), total


async def count_phrases() -> dict[str, int]:
    async with conn().execute("SELECT kind, COUNT(*) AS n FROM phrases GROUP BY kind") as cur:
        return {r["kind"]: r["n"] for r in await cur.fetchall()}


async def get_phrase(phrase_id: int) -> aiosqlite.Row | None:
    async with conn().execute("SELECT * FROM phrases WHERE id = ?", (phrase_id,)) as cur:
        return await cur.fetchone()


async def delete_phrase(phrase_id: int) -> None:
    await conn().execute("DELETE FROM phrases WHERE id = ?", (phrase_id,))
    await conn().commit()


# ---------- реклама ----------

async def create_ad(title: str, media_kind: str, file_id: str, text_html: str,
                    buttons: list, interval: int) -> int:
    cur = await conn().execute(
        "INSERT INTO ads (title, media_kind, file_id, text_html, buttons, interval, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (title, media_kind, file_id, text_html, json.dumps(buttons, ensure_ascii=False), interval, time.time()))
    await conn().commit()
    return cur.lastrowid


async def get_ad(ad_id: int) -> aiosqlite.Row | None:
    async with conn().execute("SELECT * FROM ads WHERE id = ?", (ad_id,)) as cur:
        return await cur.fetchone()


async def list_ads(enabled_only: bool = False) -> list[aiosqlite.Row]:
    sql = "SELECT * FROM ads" + (" WHERE enabled = 1" if enabled_only else "") + " ORDER BY id"
    async with conn().execute(sql) as cur:
        return list(await cur.fetchall())


async def update_ad(ad_id: int, **fields) -> None:
    bad = set(fields) - AD_FIELDS
    if bad:
        raise ValueError(f"неизвестные поля рекламы: {bad}")
    if "buttons" in fields and not isinstance(fields["buttons"], str):
        fields["buttons"] = json.dumps(fields["buttons"], ensure_ascii=False)
    sets = ", ".join(f"{k} = ?" for k in fields)
    await conn().execute(f"UPDATE ads SET {sets} WHERE id = ?", (*fields.values(), ad_id))
    await conn().commit()


async def delete_ad(ad_id: int) -> None:
    await conn().execute("DELETE FROM ads WHERE id = ?", (ad_id,))
    await conn().execute("DELETE FROM ad_sends WHERE ad_id = ?", (ad_id,))
    await conn().commit()


async def get_ad_send(ad_id: int, chat_id: int) -> aiosqlite.Row | None:
    async with conn().execute("SELECT * FROM ad_sends WHERE ad_id = ? AND chat_id = ?", (ad_id, chat_id)) as cur:
        return await cur.fetchone()


async def set_ad_send(ad_id: int, chat_id: int, message_id: int) -> None:
    await conn().execute(
        "INSERT INTO ad_sends (ad_id, chat_id, last_sent, message_id) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(ad_id, chat_id) DO UPDATE SET last_sent = excluded.last_sent, message_id = excluded.message_id",
        (ad_id, chat_id, time.time(), message_id))
    await conn().commit()


# ---------- расход на ИИ ----------

async def spent_today() -> float:
    async with conn().execute("SELECT usd FROM spend WHERE day = ?", (today(),)) as cur:
        row = await cur.fetchone()
    return row["usd"] if row else 0.0


async def add_spend(usd: float, tok_in: int, tok_out: int) -> None:
    await conn().execute(
        "INSERT INTO spend (day, usd, requests, tok_in, tok_out) VALUES (?, ?, 1, ?, ?) "
        "ON CONFLICT(day) DO UPDATE SET usd = usd + excluded.usd, requests = requests + 1, "
        "tok_in = tok_in + excluded.tok_in, tok_out = tok_out + excluded.tok_out",
        (today(), usd, tok_in, tok_out))
    await conn().commit()


async def rescale_old_spend() -> None:
    """Один раз после перехода на честные цены: дни, посчитанные по старым ценам (0.30/1.20 без кэша),
    уменьшаем до реальных. Коэффициент 0.36 взят из сверки со счётом DeepSeek ($0.30 против $0.837)."""
    if await kv_get("spend_rescaled") == "1":
        return
    await conn().execute("UPDATE spend SET usd = usd * 0.36")
    await conn().commit()
    await kv_set("spend_rescaled", "1")


async def add_ai_log(chat_id: int, kind: str, usd: float) -> None:
    hour = datetime.now(config.TZ).hour
    await conn().execute(
        "INSERT INTO ai_log (day, hour, chat_id, kind, requests, usd) VALUES (?, ?, ?, ?, 1, ?) "
        "ON CONFLICT(day, hour, chat_id, kind) DO UPDATE SET requests = requests + 1, usd = usd + excluded.usd",
        (today(), hour, chat_id, kind, usd))
    await conn().commit()


async def ai_breakdown(day: str, by: str) -> list[aiosqlite.Row]:
    """Расход за день, сгруппированный по hour, chat_id или kind."""
    assert by in ("hour", "chat_id", "kind")
    async with conn().execute(f"SELECT {by} AS k, SUM(requests) AS requests, SUM(usd) AS usd FROM ai_log "
                              f"WHERE day = ? GROUP BY {by} ORDER BY {'k' if by == 'hour' else 'usd DESC'}",
                              (day,)) as cur:
        return list(await cur.fetchall())


async def prune_ai_log(keep_days: int = 40) -> None:
    cutoff = (datetime.now(config.TZ) - timedelta(days=keep_days)).strftime("%Y-%m-%d")
    await conn().execute("DELETE FROM ai_log WHERE day < ?", (cutoff,))
    await conn().commit()


async def spend_report(days: int = 30) -> list[aiosqlite.Row]:
    async with conn().execute("SELECT * FROM spend ORDER BY day DESC LIMIT ?", (days,)) as cur:
        return list(await cur.fetchall())


# ---------- игры ----------

async def get_couple(chat_id: int, day: str) -> aiosqlite.Row | None:
    async with conn().execute("SELECT * FROM couples WHERE chat_id = ? AND day = ?", (chat_id, day)) as cur:
        return await cur.fetchone()


async def set_couple(chat_id: int, day: str, user1: int, user2: int) -> None:
    await conn().execute("INSERT OR REPLACE INTO couples (chat_id, day, user1, user2) VALUES (?, ?, ?, ?)",
                         (chat_id, day, user1, user2))
    await conn().commit()


# ---------- статистика по дням ----------

async def add_daily(chat_id: int, user_id: int, name: str, mat: bool) -> None:
    await conn().execute(
        "INSERT INTO daily_stats (chat_id, day, user_id, name, msgs, mat) VALUES (?, ?, ?, ?, 1, ?) "
        "ON CONFLICT(chat_id, day, user_id) DO UPDATE SET name = excluded.name, msgs = msgs + 1, "
        "mat = mat + excluded.mat", (chat_id, today(), user_id, name, int(mat)))
    await conn().commit()


async def add_laugh(chat_id: int, user_id: int, name: str) -> None:
    await conn().execute(
        "INSERT INTO daily_stats (chat_id, day, user_id, name, laughs) VALUES (?, ?, ?, ?, 1) "
        "ON CONFLICT(chat_id, day, user_id) DO UPDATE SET laughs = laughs + 1", (chat_id, today(), user_id, name))
    await conn().commit()


async def daily_stats(chat_id: int, day: str) -> list[aiosqlite.Row]:
    async with conn().execute("SELECT * FROM daily_stats WHERE chat_id = ? AND day = ?", (chat_id, day)) as cur:
        return list(await cur.fetchall())


async def history_since(chat_id: int, since: float, limit: int = 2000) -> list[aiosqlite.Row]:
    async with conn().execute(
            "SELECT * FROM history WHERE chat_id = ? AND ts >= ? ORDER BY id DESC LIMIT ?",
            (chat_id, since, limit)) as cur:
        rows = list(await cur.fetchall())
    rows.reverse()
    return rows


async def chat_message_count(chat_id: int, since: float) -> int:
    async with conn().execute("SELECT COUNT(*) FROM history WHERE chat_id = ? AND ts >= ? AND is_bot = 0",
                              (chat_id, since)) as cur:
        return (await cur.fetchone())[0]


async def top_reply_pair(chat_id: int, since: float, bot_id: int) -> tuple[int, int, int] | None:
    """Двое, кто больше всех отвечал друг другу: (id1, id2, сколько раз)."""
    async with conn().execute(
            "SELECT MIN(user_id, reply_user_id) AS a, MAX(user_id, reply_user_id) AS b, COUNT(*) AS n "
            "FROM history WHERE chat_id = ? AND ts >= ? AND is_bot = 0 AND reply_user_id NOT IN (0, ?) "
            "AND reply_user_id != user_id GROUP BY a, b ORDER BY n DESC LIMIT 1", (chat_id, since, bot_id)) as cur:
        row = await cur.fetchone()
    return (row["a"], row["b"], row["n"]) if row else None


# ---------- реакции ----------

async def add_reaction(chat_id: int, message_id: int, delta: int | None = None, total: int | None = None) -> None:
    """Реакция на сообщение: delta (+1/-1 от одного человека) или сразу total.
    Автора и текст берём из истории, реакции на слишком старые сообщения не считаем."""
    async with conn().execute("SELECT * FROM history WHERE chat_id = ? AND message_id = ? AND is_bot = 0",
                              (chat_id, message_id)) as cur:
        src = await cur.fetchone()
    if src is None:
        return
    if total is not None:
        update, first, arg = "excluded.total", max(0, total), max(0, total)
    else:
        update, first, arg = "MAX(0, total + ?)", max(0, delta or 0), delta or 0
    params = [chat_id, message_id, src["user_id"], src["name"], src["text"], src["ts"], first]
    if total is None:
        params.append(arg)
    await conn().execute(
        "INSERT INTO msg_reacts (chat_id, message_id, user_id, name, text, ts, total) VALUES (?, ?, ?, ?, ?, ?, ?) "
        f"ON CONFLICT(chat_id, message_id) DO UPDATE SET total = {update}", params)
    await conn().commit()


async def top_reacted(chat_id: int, since: float) -> aiosqlite.Row | None:
    async with conn().execute("SELECT * FROM msg_reacts WHERE chat_id = ? AND ts >= ? AND total > 0 "
                              "ORDER BY total DESC LIMIT 1", (chat_id, since)) as cur:
        return await cur.fetchone()


async def reacts_by_user(chat_id: int, since: float) -> dict[int, int]:
    async with conn().execute("SELECT user_id, SUM(total) AS n FROM msg_reacts WHERE chat_id = ? AND ts >= ? "
                              "GROUP BY user_id", (chat_id, since)) as cur:
        return {r["user_id"]: r["n"] for r in await cur.fetchall()}


# ---------- «как вам пара» ----------

async def create_poll(chat_id: int, user1: int, user2: int, name1: str, name2: str) -> int:
    cur = await conn().execute(
        "INSERT INTO pair_polls (chat_id, user1, user2, name1, name2, created) VALUES (?, ?, ?, ?, ?, ?)",
        (chat_id, user1, user2, name1, name2, time.time()))
    await conn().commit()
    return cur.lastrowid


async def get_poll(poll_id: int) -> aiosqlite.Row | None:
    async with conn().execute("SELECT * FROM pair_polls WHERE id = ?", (poll_id,)) as cur:
        return await cur.fetchone()


async def set_poll_message(poll_id: int, message_id: int) -> None:
    await conn().execute("UPDATE pair_polls SET message_id = ? WHERE id = ?", (message_id, poll_id))
    await conn().commit()


async def vote_poll(poll_id: int, user_id: int, vote: int) -> None:
    await conn().execute("INSERT OR REPLACE INTO pair_votes (poll_id, user_id, vote) VALUES (?, ?, ?)",
                         (poll_id, user_id, vote))
    await conn().commit()


async def poll_counts(poll_id: int) -> tuple[int, int]:
    async with conn().execute("SELECT SUM(vote = 1) AS y, SUM(vote = 0) AS n FROM pair_votes WHERE poll_id = ?",
                              (poll_id,)) as cur:
        row = await cur.fetchone()
    return row["y"] or 0, row["n"] or 0


async def polls_to_close(older_than: float) -> list[aiosqlite.Row]:
    async with conn().execute("SELECT * FROM pair_polls WHERE closed = 0 AND created <= ?", (older_than,)) as cur:
        return list(await cur.fetchall())


async def open_poll(chat_id: int) -> aiosqlite.Row | None:
    async with conn().execute("SELECT * FROM pair_polls WHERE chat_id = ? AND closed = 0 LIMIT 1", (chat_id,)) as cur:
        return await cur.fetchone()


async def close_poll(poll_id: int) -> None:
    await conn().execute("UPDATE pair_polls SET closed = 1 WHERE id = ?", (poll_id,))
    await conn().commit()


# ---------- репутация ----------

async def rep_allowed(chat_id: int, giver: int, receiver: int, now: float) -> bool:
    """Одному и тому же человеку не чаще раза в час, всего не больше 30 в сутки."""
    async with conn().execute(
            "SELECT SUM(receiver = ? AND ts >= ?) AS same, COUNT(*) AS total FROM rep_log "
            "WHERE chat_id = ? AND giver = ? AND ts >= ?",
            (receiver, now - 3600, chat_id, giver, now - 86400)) as cur:
        row = await cur.fetchone()
    return not (row["same"] or 0) and (row["total"] or 0) < 30


async def rep_change(chat_id: int, giver: int, receiver: int, delta: int) -> int:
    now = time.time()
    await conn().execute("INSERT INTO rep_log (chat_id, giver, receiver, ts) VALUES (?, ?, ?, ?)",
                         (chat_id, giver, receiver, now))
    await conn().execute("DELETE FROM rep_log WHERE ts < ?", (now - 2 * 86400,))
    await conn().execute(
        "INSERT INTO rep_points (chat_id, user_id, points) VALUES (?, ?, ?) "
        "ON CONFLICT(chat_id, user_id) DO UPDATE SET points = points + excluded.points", (chat_id, receiver, delta))
    await conn().commit()
    return await rep_get(chat_id, receiver)


async def rep_get(chat_id: int, user_id: int) -> int:
    async with conn().execute("SELECT points FROM rep_points WHERE chat_id = ? AND user_id = ?",
                              (chat_id, user_id)) as cur:
        row = await cur.fetchone()
    return row["points"] if row else 0


async def rep_top(chat_id: int, limit: int = 10) -> list[aiosqlite.Row]:
    async with conn().execute(
            "SELECT r.user_id, r.points, COALESCE(u.name, 'кто-то') AS name FROM rep_points r "
            "LEFT JOIN users u ON u.chat_id = r.chat_id AND u.user_id = r.user_id "
            "WHERE r.chat_id = ? AND r.points != 0 ORDER BY r.points DESC LIMIT ?", (chat_id, limit)) as cur:
        return list(await cur.fetchall())


# ---------- викторина ----------

async def quiz_add(chat_id: int, user_id: int, points: int) -> None:
    await conn().execute(
        "INSERT INTO quiz_scores (chat_id, user_id, points) VALUES (?, ?, ?) "
        "ON CONFLICT(chat_id, user_id) DO UPDATE SET points = points + excluded.points", (chat_id, user_id, points))
    await conn().commit()


async def quiz_top(chat_id: int, limit: int = 10) -> list[aiosqlite.Row]:
    async with conn().execute(
            "SELECT q.user_id, q.points, COALESCE(u.name, 'кто-то') AS name FROM quiz_scores q "
            "LEFT JOIN users u ON u.chat_id = q.chat_id AND u.user_id = q.user_id "
            "WHERE q.chat_id = ? ORDER BY q.points DESC LIMIT ?", (chat_id, limit)) as cur:
        return list(await cur.fetchall())


# ---------- дни рождения ----------

async def set_birthday(chat_id: int, user_id: int, mmdd: str) -> None:
    await conn().execute("UPDATE users SET birthday = ? WHERE chat_id = ? AND user_id = ?", (mmdd, chat_id, user_id))
    await conn().commit()


async def birthdays_today(chat_id: int, mmdd: str, year: int) -> list[aiosqlite.Row]:
    """Именинники, которых ещё не поздравили и кто появлялся в чате за последние 2 месяца."""
    async with conn().execute(
            "SELECT * FROM users WHERE chat_id = ? AND birthday = ? AND bday_year != ? AND last_seen >= ?",
            (chat_id, mmdd, year, time.time() - 60 * 86400)) as cur:
        return list(await cur.fetchall())


async def mark_bday(chat_id: int, user_id: int, year: int) -> None:
    await conn().execute("UPDATE users SET bday_year = ? WHERE chat_id = ? AND user_id = ?", (year, chat_id, user_id))
    await conn().commit()


async def all_birthdays(chat_id: int) -> list[aiosqlite.Row]:
    async with conn().execute("SELECT * FROM users WHERE chat_id = ? AND birthday != ''", (chat_id,)) as cur:
        return list(await cur.fetchall())


async def find_user(chat_id: int, query: str) -> aiosqlite.Row | None:
    """Ищет участника по @username или по имени (первое совпадение среди недавно писавших)."""
    q = query.strip().lstrip("@").lower()
    if not q:
        return None
    async with conn().execute(
            "SELECT * FROM users WHERE chat_id = ? AND (lower(username) = ? OR lower(name) = ? OR lower(name) LIKE ?) "
            "ORDER BY last_seen DESC LIMIT 1", (chat_id, q, q, q + "%")) as cur:
        return await cur.fetchone()


# ---------- экраны в личке (редактируются в супер-админке) ----------

async def get_screen(key: str) -> aiosqlite.Row | None:
    async with conn().execute("SELECT * FROM screens WHERE key = ?", (key,)) as cur:
        return await cur.fetchone()


async def save_screen(key: str, text_html: str, photo: str, buttons: list) -> None:
    await conn().execute(
        "INSERT INTO screens (key, text_html, photo, buttons) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(key) DO UPDATE SET text_html = excluded.text_html, photo = excluded.photo, "
        "buttons = excluded.buttons", (key, text_html, photo, json.dumps(buttons, ensure_ascii=False)))
    await conn().commit()


async def reset_screen(key: str) -> None:
    await conn().execute("DELETE FROM screens WHERE key = ?", (key,))
    await conn().commit()


# ---------- кто писал боту в личку (для рассылок и охвата) ----------

async def touch_dm(user_id: int, name: str, username: str) -> None:
    now = time.time()
    await conn().execute(
        "INSERT INTO dm_users (user_id, name, username, started, last_seen) VALUES (?, ?, ?, ?, ?) "
        "ON CONFLICT(user_id) DO UPDATE SET name = excluded.name, username = excluded.username, "
        "last_seen = excluded.last_seen, blocked = 0", (user_id, name, username, now, now))
    await conn().commit()


async def dm_user_ids() -> list[int]:
    async with conn().execute("SELECT user_id FROM dm_users WHERE blocked = 0") as cur:
        return [r[0] for r in await cur.fetchall()]


async def mark_dm_blocked(user_id: int) -> None:
    await conn().execute("UPDATE dm_users SET blocked = 1 WHERE user_id = ?", (user_id,))
    await conn().commit()


async def reach() -> dict:
    """Охват для рекламы: сколько чатов, участников (по последнему подсчёту) и людей в личке."""
    chats = await list_chats()
    async with conn().execute("SELECT COUNT(*) FROM dm_users WHERE blocked = 0") as cur:
        dm = (await cur.fetchone())[0]
    return {"chats": len(chats), "members": sum(c["members"] for c in chats), "dm": dm}


# ---------- форматы рекламы и заказы ----------

PRODUCT_FIELDS = {"title", "price", "days", "enabled", "sort"}
ORDER_FIELDS = {"target", "status", "amount", "tx", "paid_at", "next_run", "runs_left", "result", "media_kind", "file_id",
                "text_html", "buttons"}


async def seed_products(defaults: list[tuple]) -> None:
    async with conn().execute("SELECT COUNT(*) FROM ad_products") as cur:
        if (await cur.fetchone())[0]:
            return
    await conn().executemany("INSERT INTO ad_products (kind, title, price, days, sort) VALUES (?, ?, ?, ?, ?)",
                             defaults)
    await conn().commit()


async def ensure_product(kind: str, title: str, price: float, days: int, sort: int) -> None:
    """Добавить формат, если такого ещё нет (для аренды и своего бота в уже работающей базе)."""
    async with conn().execute("SELECT 1 FROM ad_products WHERE kind = ?", (kind,)) as cur:
        if await cur.fetchone():
            return
    await conn().execute("INSERT INTO ad_products (kind, title, price, days, sort) VALUES (?, ?, ?, ?, ?)",
                         (kind, title, price, days, sort))
    await conn().commit()


async def product_by_kind(kind: str) -> aiosqlite.Row | None:
    async with conn().execute("SELECT * FROM ad_products WHERE kind = ? ORDER BY id LIMIT 1", (kind,)) as cur:
        return await cur.fetchone()


async def products(enabled_only: bool = True) -> list[aiosqlite.Row]:
    sql = "SELECT * FROM ad_products" + (" WHERE enabled = 1" if enabled_only else "") + " ORDER BY sort, id"
    async with conn().execute(sql) as cur:
        return list(await cur.fetchall())


async def get_product(pid: int) -> aiosqlite.Row | None:
    async with conn().execute("SELECT * FROM ad_products WHERE id = ?", (pid,)) as cur:
        return await cur.fetchone()


async def update_product(pid: int, **fields) -> None:
    if set(fields) - PRODUCT_FIELDS:
        raise ValueError("неизвестные поля формата")
    sets = ", ".join(f"{k} = ?" for k in fields)
    await conn().execute(f"UPDATE ad_products SET {sets} WHERE id = ?", (*fields.values(), pid))
    await conn().commit()


async def create_order(user_id: int, user_name: str, kind: str, title: str, price: float, days: int,
                       media_kind: str, file_id: str, text_html: str, buttons: list, status: str,
                       target: int = 0) -> int:
    cur = await conn().execute(
        "INSERT INTO orders (user_id, user_name, kind, title, price, days, media_kind, file_id, text_html, buttons, "
        "status, created, target) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (user_id, user_name, kind, title, price, days, media_kind, file_id, text_html,
         json.dumps(buttons, ensure_ascii=False), status, time.time(), target))
    await conn().commit()
    return cur.lastrowid


async def get_order(oid: int) -> aiosqlite.Row | None:
    async with conn().execute("SELECT * FROM orders WHERE id = ?", (oid,)) as cur:
        return await cur.fetchone()


async def update_order(oid: int, **fields) -> None:
    if set(fields) - ORDER_FIELDS:
        raise ValueError("неизвестные поля заказа")
    if "buttons" in fields and not isinstance(fields["buttons"], str):
        fields["buttons"] = json.dumps(fields["buttons"], ensure_ascii=False)
    sets = ", ".join(f"{k} = ?" for k in fields)
    await conn().execute(f"UPDATE orders SET {sets} WHERE id = ?", (*fields.values(), oid))
    await conn().commit()


async def orders_by_status(*statuses: str, limit: int = 100) -> list[aiosqlite.Row]:
    marks = ",".join("?" * len(statuses))
    async with conn().execute(f"SELECT * FROM orders WHERE status IN ({marks}) ORDER BY id DESC LIMIT ?",
                              (*statuses, limit)) as cur:
        return list(await cur.fetchall())


async def amount_taken(amount: int) -> bool:
    async with conn().execute("SELECT 1 FROM orders WHERE status = 'awaiting' AND amount = ?", (amount,)) as cur:
        return await cur.fetchone() is not None


async def tx_seen(tx: str) -> bool:
    async with conn().execute("SELECT 1 FROM ton_seen WHERE tx = ?", (tx,)) as cur:
        return await cur.fetchone() is not None


async def mark_tx(tx: str) -> None:
    await conn().execute("INSERT OR IGNORE INTO ton_seen (tx, ts) VALUES (?, ?)", (tx, time.time()))
    await conn().commit()


async def add_pin(chat_id: int, message_id: int, unpin_at: float) -> None:
    await conn().execute("INSERT INTO pins (chat_id, message_id, unpin_at) VALUES (?, ?, ?)",
                         (chat_id, message_id, unpin_at))
    await conn().commit()


async def due_pins(now: float) -> list[aiosqlite.Row]:
    async with conn().execute("SELECT * FROM pins WHERE unpin_at <= ?", (now,)) as cur:
        return list(await cur.fetchall())


async def delete_pin(pin_id: int) -> None:
    await conn().execute("DELETE FROM pins WHERE id = ?", (pin_id,))
    await conn().commit()


# ---------- магазин за звёзды ----------

async def seed_shop(defaults: list[tuple]) -> None:
    keys = [d[0] for d in defaults]
    # товары, которых больше нет в магазине, убираем
    await conn().execute(f"DELETE FROM shop_items WHERE key NOT IN ({','.join('?' * len(keys))})", keys)
    await conn().executemany("INSERT OR IGNORE INTO shop_items (key, title, stars, sort) VALUES (?, ?, ?, ?)",
                             defaults)
    await conn().commit()


async def shop_items(enabled_only: bool = True) -> list[aiosqlite.Row]:
    sql = "SELECT * FROM shop_items" + (" WHERE enabled = 1" if enabled_only else "") + " ORDER BY sort"
    async with conn().execute(sql) as cur:
        return list(await cur.fetchall())


async def shop_item(key: str) -> aiosqlite.Row | None:
    async with conn().execute("SELECT * FROM shop_items WHERE key = ?", (key,)) as cur:
        return await cur.fetchone()


async def update_shop_item(key: str, **fields) -> None:
    if set(fields) - {"title", "stars", "enabled"}:
        raise ValueError("неизвестные поля товара")
    sets = ", ".join(f"{k} = ?" for k in fields)
    await conn().execute(f"UPDATE shop_items SET {sets} WHERE key = ?", (*fields.values(), key))
    await conn().commit()


async def add_star_payment(user_id: int, name: str, item: str, stars: int, charge_id: str, payload: str) -> int:
    cur = await conn().execute(
        "INSERT INTO star_payments (user_id, name, item, stars, charge_id, payload, ts) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (user_id, name, item, stars, charge_id, payload, time.time()))
    await conn().commit()
    return cur.lastrowid


async def star_payments(limit: int = 20) -> list[aiosqlite.Row]:
    async with conn().execute("SELECT * FROM star_payments ORDER BY id DESC LIMIT ?", (limit,)) as cur:
        return list(await cur.fetchall())


async def get_star_payment(pid: int) -> aiosqlite.Row | None:
    async with conn().execute("SELECT * FROM star_payments WHERE id = ?", (pid,)) as cur:
        return await cur.fetchone()


async def mark_refunded(pid: int) -> None:
    await conn().execute("UPDATE star_payments SET refunded = 1 WHERE id = ?", (pid,))
    await conn().commit()


async def donors_top(limit: int = 10, user_ids: list[int] | None = None) -> list[aiosqlite.Row]:
    """Топ по всем звёздам, без возвратов. user_ids: только среди этих людей (участники чата)."""
    where, params = "refunded = 0", []
    if user_ids is not None:
        if not user_ids:
            return []
        where += f" AND user_id IN ({','.join('?' * len(user_ids))})"
        params = list(user_ids)
    async with conn().execute(
            f"SELECT user_id, MAX(name) AS name, SUM(stars) AS stars FROM star_payments WHERE {where} "
            "GROUP BY user_id ORDER BY stars DESC LIMIT ?", (*params, limit)) as cur:
        return list(await cur.fetchall())


async def get_perks(user_id: int) -> aiosqlite.Row | None:
    async with conn().execute("SELECT * FROM perks WHERE user_id = ?", (user_id,)) as cur:
        return await cur.fetchone()


async def set_perks(user_id: int, **fields) -> None:
    if set(fields) - {"title", "title_until", "shield_until", "vip_until", "emoji_id", "emoji_alt", "nick",
                          "look_forever"}:
        raise ValueError("неизвестные поля")
    await conn().execute("INSERT OR IGNORE INTO perks (user_id) VALUES (?)", (user_id,))
    sets = ", ".join(f"{k} = ?" for k in fields)
    await conn().execute(f"UPDATE perks SET {sets} WHERE user_id = ?", (*fields.values(), user_id))
    await conn().commit()


async def active_titles(user_ids: list[int]) -> dict[int, str]:
    if not user_ids:
        return {}
    marks = ",".join("?" * len(user_ids))
    async with conn().execute(f"SELECT user_id, title FROM perks WHERE user_id IN ({marks}) AND title != '' "
                              "AND title_until > ?", (*user_ids, time.time())) as cur:
        return {r["user_id"]: r["title"] for r in await cur.fetchall()}


async def chat_user_ids(chat_id: int) -> list[int]:
    async with conn().execute("SELECT user_id FROM users WHERE chat_id = ?", (chat_id,)) as cur:
        return [r[0] for r in await cur.fetchall()]


async def vip_looks() -> list[aiosqlite.Row]:
    async with conn().execute("SELECT user_id, emoji_id, emoji_alt, nick FROM perks WHERE vip_until > ? OR look_forever = 1",
                              (time.time(),)) as cur:
        return list(await cur.fetchall())


async def vip_ids(user_ids: list[int]) -> set[int]:
    if not user_ids:
        return set()
    marks = ",".join("?" * len(user_ids))
    async with conn().execute(f"SELECT user_id FROM perks WHERE user_id IN ({marks}) AND vip_until > ?",
                              (*user_ids, time.time())) as cur:
        return {r[0] for r in await cur.fetchall()}


async def set_chat_title(chat_id: int, user_id: int, title: str, until: float) -> None:
    await conn().execute("INSERT OR REPLACE INTO chat_titles (chat_id, user_id, title, until) VALUES (?, ?, ?, ?)",
                         (chat_id, user_id, title, until))
    await conn().commit()


async def get_chat_title(chat_id: int, user_id: int) -> aiosqlite.Row | None:
    async with conn().execute("SELECT * FROM chat_titles WHERE chat_id = ? AND user_id = ?",
                              (chat_id, user_id)) as cur:
        return await cur.fetchone()


async def expired_titles(now: float) -> list[aiosqlite.Row]:
    async with conn().execute("SELECT * FROM chat_titles WHERE until <= ?", (now,)) as cur:
        return list(await cur.fetchall())


async def delete_chat_title(chat_id: int, user_id: int) -> None:
    await conn().execute("DELETE FROM chat_titles WHERE chat_id = ? AND user_id = ?", (chat_id, user_id))
    await conn().commit()


async def stars_total(since: float = 0) -> int:
    async with conn().execute("SELECT COALESCE(SUM(stars), 0) FROM star_payments WHERE refunded = 0 AND ts >= ?",
                              (since,)) as cur:
        return (await cur.fetchone())[0]


# ---------- триггеры: слово в чате → готовый ответ ----------

async def add_trigger(chat_id: int, word: str, media_kind: str, file_id: str, text_html: str) -> int:
    await conn().execute("DELETE FROM triggers WHERE chat_id = ? AND word = ?", (chat_id, word))
    cur = await conn().execute(
        "INSERT INTO triggers (chat_id, word, media_kind, file_id, text_html, created) VALUES (?, ?, ?, ?, ?, ?)",
        (chat_id, word, media_kind, file_id, text_html, time.time()))
    await conn().commit()
    return cur.lastrowid


async def list_triggers(chat_id: int) -> list[aiosqlite.Row]:
    async with conn().execute("SELECT * FROM triggers WHERE chat_id = ? ORDER BY word", (chat_id,)) as cur:
        return list(await cur.fetchall())


async def get_trigger(tid: int) -> aiosqlite.Row | None:
    async with conn().execute("SELECT * FROM triggers WHERE id = ?", (tid,)) as cur:
        return await cur.fetchone()


async def delete_trigger(tid: int) -> None:
    await conn().execute("DELETE FROM triggers WHERE id = ?", (tid,))
    await conn().commit()


# ---------- поддержка: переписки с людьми ----------

async def support_add(user_id: int, name: str, username: str, topic: str, direction: str, text: str) -> None:
    now = time.time()
    status = "new" if direction == "in" else "answered"
    await conn().execute(
        "INSERT INTO support_threads (user_id, name, username, topic, status, last_ts) VALUES (?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(user_id) DO UPDATE SET status = excluded.status, last_ts = excluded.last_ts, "
        "name = CASE WHEN excluded.name != '' THEN excluded.name ELSE name END, "
        "username = CASE WHEN excluded.name != '' THEN excluded.username ELSE username END, "
        "topic = CASE WHEN excluded.topic != '' THEN excluded.topic ELSE topic END",
        (user_id, name, username, topic, status, now))
    await conn().execute("INSERT INTO support_msgs (user_id, direction, text, ts) VALUES (?, ?, ?, ?)",
                         (user_id, direction, text[:2000], now))
    await conn().commit()


async def support_threads(closed: bool = False, limit: int = 30) -> list[aiosqlite.Row]:
    sql = ("SELECT * FROM support_threads WHERE status " + ("= 'closed'" if closed else "!= 'closed'")
           + " ORDER BY (status = 'new') DESC, last_ts DESC LIMIT ?")
    async with conn().execute(sql, (limit,)) as cur:
        return list(await cur.fetchall())


async def support_thread(user_id: int) -> aiosqlite.Row | None:
    async with conn().execute("SELECT * FROM support_threads WHERE user_id = ?", (user_id,)) as cur:
        return await cur.fetchone()


async def support_msgs(user_id: int, limit: int = 8) -> list[aiosqlite.Row]:
    async with conn().execute("SELECT * FROM support_msgs WHERE user_id = ? ORDER BY id DESC LIMIT ?",
                              (user_id, limit)) as cur:
        rows = list(await cur.fetchall())
    rows.reverse()
    return rows


async def support_close(user_id: int) -> None:
    await conn().execute("UPDATE support_threads SET status = 'closed' WHERE user_id = ?", (user_id,))
    await conn().commit()


async def support_new_count() -> int:
    async with conn().execute("SELECT COUNT(*) FROM support_threads WHERE status = 'new'") as cur:
        return (await cur.fetchone())[0]


# ---------- премиум-эмодзи бота ----------

async def emoji_add(emoji_id: str, alt: str) -> None:
    await conn().execute("INSERT OR REPLACE INTO emoji_pack (emoji_id, alt) VALUES (?, ?)", (emoji_id, alt))
    await conn().commit()


async def emoji_list() -> list[aiosqlite.Row]:
    async with conn().execute("SELECT * FROM emoji_pack ORDER BY rowid") as cur:
        return list(await cur.fetchall())


async def emoji_clear() -> None:
    await conn().execute("DELETE FROM emoji_pack")
    await conn().commit()


# ---------- зазывала: свой список людей ----------

async def call_add(chat_id: int, user_id: int, name: str) -> None:
    await conn().execute("INSERT OR REPLACE INTO call_list (chat_id, user_id, name) VALUES (?, ?, ?)",
                         (chat_id, user_id, name))
    await conn().commit()


async def call_remove(chat_id: int, user_id: int) -> None:
    await conn().execute("DELETE FROM call_list WHERE chat_id = ? AND user_id = ?", (chat_id, user_id))
    await conn().commit()


async def call_list(chat_id: int) -> list[aiosqlite.Row]:
    async with conn().execute("SELECT * FROM call_list WHERE chat_id = ? ORDER BY name", (chat_id,)) as cur:
        return list(await cur.fetchall())


async def users_since(chat_id: int, since: float, limit: int) -> list[aiosqlite.Row]:
    """Участники, которые писали после since (since=0: все, кого бот видел)."""
    async with conn().execute(
            "SELECT * FROM users WHERE chat_id = ? AND last_seen >= ? ORDER BY last_seen DESC LIMIT ?",
            (chat_id, since, limit)) as cur:
        return list(await cur.fetchall())


# ---------- статистика и деньги для админок ----------

async def days_totals(chat_id: int, days: list[str]) -> dict[str, int]:
    """Сколько сообщений было в каждый из дней."""
    marks = ",".join("?" * len(days))
    async with conn().execute(f"SELECT day, SUM(msgs) FROM daily_stats WHERE chat_id = ? AND day IN ({marks}) "
                              "GROUP BY day", (chat_id, *days)) as cur:
        found = {r[0]: r[1] for r in await cur.fetchall()}
    return {d: found.get(d, 0) for d in days}


async def top_talkers(chat_id: int, days: list[str], limit: int = 5) -> list[aiosqlite.Row]:
    marks = ",".join("?" * len(days))
    async with conn().execute(
            f"SELECT user_id, MAX(name) AS name, SUM(msgs) AS msgs FROM daily_stats WHERE chat_id = ? "
            f"AND day IN ({marks}) GROUP BY user_id ORDER BY msgs DESC LIMIT ?", (chat_id, *days, limit)) as cur:
        return list(await cur.fetchall())


async def known_people(chat_id: int) -> int:
    async with conn().execute("SELECT COUNT(*) FROM users WHERE chat_id = ? AND msg_count > 0", (chat_id,)) as cur:
        return (await cur.fetchone())[0]


async def paid_orders(since: float) -> list[aiosqlite.Row]:
    async with conn().execute("SELECT * FROM orders WHERE paid_at >= ? AND paid_at > 0 AND status != 'rejected'",
                              (since,)) as cur:
        return list(await cur.fetchall())


async def people_count() -> int:
    async with conn().execute("SELECT COUNT(DISTINCT user_id) FROM users WHERE msg_count > 0") as cur:
        return (await cur.fetchone())[0]


async def find_person(query: str) -> dict | None:
    """Человек по id или @username: из лички и из чатов."""
    q = query.strip().lstrip("@")
    if not q:
        return None
    if q.lstrip("-").isdigit():
        where, arg = "user_id = ?", int(q)
    else:
        where, arg = "lower(username) = ?", q.lower()
    async with conn().execute(f"SELECT user_id, name, username FROM dm_users WHERE {where}", (arg,)) as cur:
        row = await cur.fetchone()
    if row is None:
        async with conn().execute(f"SELECT user_id, name, username FROM users WHERE {where} "
                                  "ORDER BY last_seen DESC LIMIT 1", (arg,)) as cur:
            row = await cur.fetchone()
    if row is None:
        return None
    uid = row["user_id"]
    async with conn().execute("SELECT c.title FROM users u JOIN chats c ON c.chat_id = u.chat_id "
                              "WHERE u.user_id = ? AND c.active = 1", (uid,)) as cur:
        chats = [r[0] for r in await cur.fetchall()]
    async with conn().execute("SELECT 1 FROM dm_users WHERE user_id = ? AND blocked = 0", (uid,)) as cur:
        dm = await cur.fetchone() is not None
    async with conn().execute("SELECT COALESCE(SUM(stars), 0) FROM star_payments WHERE user_id = ? AND refunded = 0",
                              (uid,)) as cur:
        stars = (await cur.fetchone())[0]
    return {"user_id": uid, "name": row["name"], "username": row["username"], "chats": chats, "dm": dm,
            "stars": stars}


async def username_of(user_id: int) -> str:
    async with conn().execute("SELECT username FROM dm_users WHERE user_id = ? AND username != ''", (user_id,)) as cur:
        row = await cur.fetchone()
    if row is None:
        async with conn().execute("SELECT username FROM users WHERE user_id = ? AND username != '' "
                                  "ORDER BY last_seen DESC LIMIT 1", (user_id,)) as cur:
            row = await cur.fetchone()
    return row[0] if row else ""


# ---------- служебные настройки ----------

async def kv_get(key: str, default: str = "") -> str:
    async with conn().execute("SELECT value FROM kv WHERE key = ?", (key,)) as cur:
        row = await cur.fetchone()
    return row[0] if row else default


async def kv_set(key: str, value: str) -> None:
    await conn().execute("INSERT OR REPLACE INTO kv (key, value) VALUES (?, ?)", (key, str(value)))
    await conn().commit()


# ---------- перенос чата и экспорт настроек ----------

# что из настроек чата переносится и попадает в экспорт (без названия, id, статуса и служебных отметок)
SETTING_FIELDS = ["bot_name", "aliases", "persona", "topic", "chance", "ai_share", "cooldown", "greet", "games", "qday",
                  "revive", "qday_queue",
                  "pairpoll", "results", "results_hour", "rep", "bday", "shop", "quiz", "quiz_count", "quiet_from",
                  "quiet_to", "humor", "mat", "banned", "protect_admins", "call_text", "call_who", "call_style",
                  "call_max"]
MOVE_TABLES = ["rep_points", "quiz_scores", "call_list"]   # переносятся целиком, с заменой chat_id


async def chat_settings(chat_id: int) -> dict:
    chat = await get_chat(chat_id)
    return {f: chat[f] for f in SETTING_FIELDS if f in chat.keys()} if chat else {}


async def apply_settings(chat_id: int, data: dict) -> int:
    fields = {k: v for k, v in data.items() if k in SETTING_FIELDS}
    if fields:
        await update_chat(chat_id, **fields)
    return len(fields)


async def _columns(table: str) -> list[str]:
    async with conn().execute(f"PRAGMA table_info({table})") as cur:
        return [r[1] for r in await cur.fetchall()]


async def move_chat(src: int, dst: int) -> dict:
    """Переносит всё из старого чата в новый: настройки, людей с памятью и ДР, репутацию, викторину,
    триггеры, список зазывалы, одобрение и остаток аренды. Старый чат теряет аренду и одобрение."""
    old = await get_chat(src)
    await apply_settings(dst, await chat_settings(src))
    await update_chat(dst, approved=1, pending_since=0, rent_until=old["rent_until"], trial=old["trial"],
                      rent_warned=0, added_by=old["added_by"] or 0, added_name=old["added_name"],
                      added_username=old["added_username"])
    counts = {}
    for table in MOVE_TABLES:
        cols = [c for c in await _columns(table) if c != "chat_id"]
        names = ", ".join(cols)
        cur = await conn().execute(f"INSERT OR IGNORE INTO {table} (chat_id, {names}) "
                                   f"SELECT ?, {names} FROM {table} WHERE chat_id = ?", (dst, src))
        counts[table] = cur.rowcount
    cols = [c for c in await _columns("triggers") if c not in ("id", "chat_id")]
    names = ", ".join(cols)
    cur = await conn().execute(f"INSERT INTO triggers (chat_id, {names}) SELECT ?, {names} FROM triggers "
                               "WHERE chat_id = ? AND word NOT IN (SELECT word FROM triggers WHERE chat_id = ?)",
                               (dst, src, dst))
    counts["triggers"] = cur.rowcount
    # люди: заметки бота и дни рождения. Кого бот уже видел в новом чате, тем дописываем пустые поля
    cols = [c for c in await _columns("users") if c != "chat_id"]
    names = ", ".join(cols)
    cur = await conn().execute(f"INSERT OR IGNORE INTO users (chat_id, {names}) SELECT ?, {names} FROM users "
                               "WHERE chat_id = ?", (dst, src))
    counts["users"] = cur.rowcount
    await conn().execute(
        "UPDATE users SET notes = (SELECT o.notes FROM users o WHERE o.chat_id = ? AND o.user_id = users.user_id), "
        "birthday = COALESCE(NULLIF(birthday, ''), (SELECT o.birthday FROM users o WHERE o.chat_id = ? "
        "AND o.user_id = users.user_id)) WHERE chat_id = ? AND (notes = '' OR notes IS NULL) "
        "AND user_id IN (SELECT user_id FROM users WHERE chat_id = ?)", (src, src, dst, src))
    await conn().execute("UPDATE chats SET rent_until = 0, approved = 0, trial = 0, pending_since = 0 "
                         "WHERE chat_id = ?", (src,))
    await conn().commit()
    return counts


async def lost_chats(user_id: int) -> list[aiosqlite.Row]:
    """Чаты, где бота больше нет и которые этот человек когда-то добавил: из них можно перенести всё."""
    async with conn().execute("SELECT * FROM chats WHERE active = 0 AND added_by = ? ORDER BY title",
                              (user_id,)) as cur:
        return list(await cur.fetchall())


async def rep_place(chat_id: int, user_id: int) -> int:
    async with conn().execute(
            "SELECT COUNT(*) + 1 FROM rep_points WHERE chat_id = ? AND points > "
            "(SELECT COALESCE(MAX(points), 0) FROM rep_points WHERE chat_id = ? AND user_id = ?)",
            (chat_id, chat_id, user_id)) as cur:
        return (await cur.fetchone())[0]


async def last_message_ts(chat_id: int) -> float:
    async with conn().execute("SELECT MAX(ts) FROM history WHERE chat_id = ? AND is_bot = 0", (chat_id,)) as cur:
        return (await cur.fetchone())[0] or 0
