"""SQLite (WAL) + версионные миграции схемы."""
import logging
from pathlib import Path
from typing import Any, Iterable

import aiosqlite

log = logging.getLogger(__name__)

# Каждая миграция применяется один раз, по порядку. Новые — только добавлять в конец.
MIGRATIONS: list[str] = [
    # 1 — базовая схема
    """
    CREATE TABLE settings (
        key   TEXT PRIMARY KEY,
        value TEXT NOT NULL
    ) WITHOUT ROWID;

    CREATE TABLE media (
        id         INTEGER PRIMARY KEY,
        sha256     TEXT NOT NULL UNIQUE,
        path       TEXT NOT NULL,
        kind       TEXT NOT NULL,          -- photo | animation | video
        size       INTEGER NOT NULL,
        created_at INTEGER NOT NULL
    );

    CREATE TABLE media_file_ids (
        media_id INTEGER NOT NULL REFERENCES media(id) ON DELETE CASCADE,
        bot_id   INTEGER NOT NULL,
        file_id  TEXT NOT NULL,
        PRIMARY KEY (media_id, bot_id)
    ) WITHOUT ROWID;
    CREATE INDEX ix_media_file_ids_bot ON media_file_ids(bot_id);

    CREATE TABLE texts (
        key      TEXT PRIMARY KEY,
        html     TEXT NOT NULL DEFAULT '',
        media_id INTEGER REFERENCES media(id) ON DELETE SET NULL
    );

    CREATE TABLE buttons (
        key   TEXT PRIMARY KEY,
        label TEXT NOT NULL,
        icon  TEXT,
        style TEXT
    ) WITHOUT ROWID;

    CREATE TABLE menu_items (
        id        INTEGER PRIMARY KEY,
        parent_id INTEGER REFERENCES menu_items(id) ON DELETE CASCADE,
        kind      TEXT NOT NULL,           -- menu | tag | all | cities | search | url
        payload   TEXT,
        label     TEXT NOT NULL DEFAULT '',
        icon      TEXT,
        style     TEXT,
        html      TEXT NOT NULL DEFAULT '',
        media_id  INTEGER REFERENCES media(id) ON DELETE SET NULL,
        row       INTEGER NOT NULL DEFAULT 0,
        position  INTEGER NOT NULL DEFAULT 0,
        is_system INTEGER NOT NULL DEFAULT 0,
        is_active INTEGER NOT NULL DEFAULT 1
    );
    CREATE INDEX ix_menu_items_parent ON menu_items(parent_id, row, position);

    CREATE TABLE tags (
        id       INTEGER PRIMARY KEY,
        label    TEXT NOT NULL,
        position INTEGER NOT NULL DEFAULT 0
    );

    CREATE TABLE cities (
        id        INTEGER PRIMARY KEY,
        label     TEXT NOT NULL,
        icon      TEXT,
        style     TEXT,
        is_main   INTEGER NOT NULL DEFAULT 0,
        position  INTEGER NOT NULL DEFAULT 0,
        is_active INTEGER NOT NULL DEFAULT 1
    );
    CREATE INDEX ix_cities_order ON cities(is_active, is_main, position);

    CREATE TABLE shops (
        id         INTEGER PRIMARY KEY,
        label      TEXT NOT NULL,
        icon       TEXT,
        style      TEXT,
        html       TEXT NOT NULL DEFAULT '',
        plain      TEXT NOT NULL DEFAULT '',
        media_id   INTEGER REFERENCES media(id) ON DELETE SET NULL,
        verified   INTEGER NOT NULL DEFAULT 0,
        position   INTEGER NOT NULL DEFAULT 0,
        is_active  INTEGER NOT NULL DEFAULT 1,
        created_at INTEGER NOT NULL,
        updated_at INTEGER NOT NULL
    );
    CREATE INDEX ix_shops_active ON shops(is_active, position);

    CREATE TABLE shop_contacts (
        id       INTEGER PRIMARY KEY,
        shop_id  INTEGER NOT NULL REFERENCES shops(id) ON DELETE CASCADE,
        label    TEXT NOT NULL,
        url      TEXT NOT NULL,
        icon     TEXT,
        style    TEXT,
        position INTEGER NOT NULL DEFAULT 0
    );
    CREATE INDEX ix_shop_contacts_shop ON shop_contacts(shop_id, position);

    CREATE TABLE shop_tags (
        shop_id    INTEGER NOT NULL REFERENCES shops(id) ON DELETE CASCADE,
        tag_id     INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
        expires_at INTEGER,
        notified   INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (shop_id, tag_id)
    ) WITHOUT ROWID;
    CREATE INDEX ix_shop_tags_tag ON shop_tags(tag_id);
    CREATE INDEX ix_shop_tags_expires ON shop_tags(expires_at) WHERE expires_at IS NOT NULL;

    CREATE TABLE shop_cities (
        shop_id INTEGER NOT NULL REFERENCES shops(id) ON DELETE CASCADE,
        city_id INTEGER NOT NULL REFERENCES cities(id) ON DELETE CASCADE,
        PRIMARY KEY (shop_id, city_id)
    ) WITHOUT ROWID;
    CREATE INDEX ix_shop_cities_city ON shop_cities(city_id);

    CREATE TABLE users (
        id            INTEGER PRIMARY KEY,
        username      TEXT,
        first_name    TEXT,
        created_at    INTEGER NOT NULL,
        last_seen     INTEGER NOT NULL,
        is_banned     INTEGER NOT NULL DEFAULT 0,
        banned_until  INTEGER,
        ban_reason    TEXT,
        is_blocked    INTEGER NOT NULL DEFAULT 0,
        screen_msg_id INTEGER
    );
    CREATE INDEX ix_users_banned ON users(is_banned) WHERE is_banned = 1;
    CREATE INDEX ix_users_last_seen ON users(last_seen);
    CREATE INDEX ix_users_created ON users(created_at);
    CREATE INDEX ix_users_username ON users(username COLLATE NOCASE);

    CREATE TABLE admins (
        user_id    INTEGER PRIMARY KEY,
        perms      TEXT NOT NULL DEFAULT '',
        added_by   INTEGER,
        created_at INTEGER NOT NULL
    );

    CREATE TABLE events (
        id      INTEGER PRIMARY KEY,
        shop_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        kind    TEXT NOT NULL,             -- view
        ts      INTEGER NOT NULL
    );
    CREATE INDEX ix_events_shop_ts ON events(shop_id, ts);
    CREATE INDEX ix_events_ts ON events(ts);

    CREATE TABLE reports (
        id         INTEGER PRIMARY KEY,
        shop_id    INTEGER NOT NULL REFERENCES shops(id) ON DELETE CASCADE,
        user_id    INTEGER NOT NULL,
        text       TEXT NOT NULL,
        status     TEXT NOT NULL DEFAULT 'open',
        created_at INTEGER NOT NULL
    );
    CREATE INDEX ix_reports_status ON reports(status, created_at);
    CREATE INDEX ix_reports_user ON reports(user_id, created_at);

    CREATE TABLE admin_log (
        id       INTEGER PRIMARY KEY,
        admin_id INTEGER NOT NULL,
        action   TEXT NOT NULL,
        details  TEXT NOT NULL DEFAULT '',
        ts       INTEGER NOT NULL
    );
    CREATE INDEX ix_admin_log_ts ON admin_log(ts);
    """,
]


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._conn: aiosqlite.Connection | None = None

    @property
    def conn(self) -> aiosqlite.Connection:
        assert self._conn is not None, "database is not connected"
        return self._conn

    async def connect(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(self.path)
        self._conn.row_factory = aiosqlite.Row
        for pragma in (
            "journal_mode=WAL",
            "synchronous=NORMAL",
            "foreign_keys=ON",
            "temp_store=MEMORY",
            "cache_size=-8000",  # ~8 МБ страничного кэша, не больше
            "busy_timeout=5000",
        ):
            await self._conn.execute(f"PRAGMA {pragma}")
        await self._migrate()

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    async def _migrate(self) -> None:
        version = (await self.fetchval("PRAGMA user_version")) or 0
        for number, sql in enumerate(MIGRATIONS[version:], start=version + 1):
            log.info("Применяю миграцию %s", number)
            await self.conn.executescript(f"BEGIN;{sql}\nPRAGMA user_version={number};COMMIT;")

    async def fetchall(self, sql: str, params: Iterable[Any] = ()) -> list[aiosqlite.Row]:
        async with self.conn.execute(sql, tuple(params)) as cur:
            return list(await cur.fetchall())

    async def fetchone(self, sql: str, params: Iterable[Any] = ()) -> aiosqlite.Row | None:
        async with self.conn.execute(sql, tuple(params)) as cur:
            return await cur.fetchone()

    async def fetchval(self, sql: str, params: Iterable[Any] = ()) -> Any:
        row = await self.fetchone(sql, params)
        return row[0] if row is not None else None

    async def execute(self, sql: str, params: Iterable[Any] = ()) -> int:
        """Выполнить запрос и закоммитить. Возвращает lastrowid."""
        cur = await self.conn.execute(sql, tuple(params))
        await self.conn.commit()
        return cur.lastrowid or 0

    async def executemany(self, sql: str, rows: Iterable[Iterable[Any]]) -> None:
        await self.conn.executemany(sql, [tuple(r) for r in rows])
        await self.conn.commit()

    async def script(self, sql: str) -> None:
        await self.conn.executescript(sql)
        await self.conn.commit()

    async def backup_to(self, target: Path) -> None:
        """Консистентная копия базы (работает на живой базе)."""
        target.parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(target) as dst:
            await self.conn.backup(dst)
