"""Общий контейнер сервисов и буферы записи (чтобы не дёргать базу на каждый клик)."""
import logging
from dataclasses import dataclass, field

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError

from .catalog import Catalog, now
from .config import Config
from .db import Database
from .media import MediaStore

log = logging.getLogger(__name__)


@dataclass(slots=True)
class Screen:
    """Где у пользователя висит текущий экран бота."""
    message_id: int
    has_media: bool


@dataclass
class App:
    config: Config
    db: Database
    catalog: Catalog
    media: MediaStore
    bot: Bot
    bot_username: str = ""
    known_users: set[int] = field(default_factory=set)
    banned: dict[int, int | None] = field(default_factory=dict)  # user_id -> until (None = навсегда)
    screens: dict[int, Screen] = field(default_factory=dict)
    langs: dict[int, str] = field(default_factory=dict)  # явно выбранный язык
    last_city: dict[int, int] = field(default_factory=dict)  # «📍 Мой город»
    _seen: dict[int, tuple[int, str | None, str | None]] = field(default_factory=dict)
    _screen_ids: dict[int, int] = field(default_factory=dict)
    _events: list[tuple[int, int, str, int]] = field(default_factory=list)

    async def load_users(self) -> None:
        self.known_users = {r["id"] for r in await self.db.fetchall("SELECT id FROM users")}
        self.langs = {r["id"]: r["lang"] for r in await self.db.fetchall("SELECT id, lang FROM users WHERE lang IS NOT NULL")}
        self.last_city = {r["id"]: r["last_city"] for r in await self.db.fetchall(
            "SELECT id, last_city FROM users WHERE last_city IS NOT NULL")}
        self.banned = {
            r["id"]: r["banned_until"]
            for r in await self.db.fetchall("SELECT id, banned_until FROM users WHERE is_banned = 1")
        }

    # ---------- пользователи ----------
    async def touch_user(self, user_id: int, username: str | None, first_name: str | None,
                         telegram_lang: str | None = None) -> None:
        ts = now()
        if user_id not in self.known_users:
            self.known_users.add(user_id)
            lang = self.catalog.pick_lang(None, telegram_lang)  # язык из настроек Telegram — до ручного выбора
            self.langs.setdefault(user_id, lang)
            await self.db.execute(
                "INSERT OR IGNORE INTO users(id, username, first_name, created_at, last_seen, lang)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (user_id, username, first_name, ts, ts, lang),
            )
            return
        self._seen[user_id] = (ts, username, first_name)

    def user_lang(self, user_id: int, telegram_code: str | None) -> str:
        return self.catalog.pick_lang(self.langs.get(user_id), telegram_code)

    async def set_lang(self, user_id: int, lang: str) -> None:
        self.langs[user_id] = lang
        await self.db.execute("UPDATE users SET lang = ? WHERE id = ?", (lang, user_id))

    async def remember_city(self, user_id: int, city_id: int) -> None:
        if self.last_city.get(user_id) != city_id:
            self.last_city[user_id] = city_id
            await self.db.execute("UPDATE users SET last_city = ? WHERE id = ?", (city_id, user_id))

    # ---------- избранное ----------
    async def is_favorite(self, user_id: int, shop_id: int) -> bool:
        return bool(await self.db.fetchval(
            "SELECT 1 FROM favorites WHERE user_id = ? AND shop_id = ?", (user_id, shop_id)))

    async def toggle_favorite(self, user_id: int, shop_id: int) -> bool:
        """-> True, если магазин теперь в избранном."""
        if await self.is_favorite(user_id, shop_id):
            await self.db.execute("DELETE FROM favorites WHERE user_id = ? AND shop_id = ?", (user_id, shop_id))
            return False
        await self.db.execute("INSERT INTO favorites(user_id, shop_id, created_at) VALUES (?, ?, ?)",
                              (user_id, shop_id, now()))
        return True

    async def favorite_ids(self, user_id: int) -> list[int]:
        rows = await self.db.fetchall(
            "SELECT shop_id FROM favorites WHERE user_id = ? ORDER BY created_at DESC", (user_id,))
        return [r["shop_id"] for r in rows]

    def is_banned(self, user_id: int) -> bool:
        if user_id not in self.banned:
            return False
        until = self.banned[user_id]
        return until is None or until > now()

    async def ban(self, user_id: int, until: int | None, reason: str) -> None:
        if user_id not in self.known_users:
            self.known_users.add(user_id)
            await self.db.execute(
                "INSERT OR IGNORE INTO users(id, created_at, last_seen) VALUES (?, ?, ?)", (user_id, now(), now())
            )
        self.banned[user_id] = until
        await self.db.execute(
            "UPDATE users SET is_banned = 1, banned_until = ?, ban_reason = ? WHERE id = ?", (until, reason, user_id)
        )

    async def unban(self, user_id: int) -> None:
        self.banned.pop(user_id, None)
        await self.db.execute(
            "UPDATE users SET is_banned = 0, banned_until = NULL, ban_reason = NULL WHERE id = ?", (user_id,)
        )

    # ---------- экраны ----------
    def set_screen(self, user_id: int, message_id: int, has_media: bool) -> None:
        self.screens[user_id] = Screen(message_id, has_media)
        self._screen_ids[user_id] = message_id

    async def last_screen_id(self, user_id: int) -> int | None:
        """Id прошлого экрана — из памяти или (после перезапуска) из базы."""
        if user_id in self.screens:
            return self.screens[user_id].message_id
        return await self.db.fetchval("SELECT screen_msg_id FROM users WHERE id = ?", (user_id,))

    # ---------- статистика ----------
    def track(self, shop_id: int, user_id: int, kind: str = "view") -> None:
        self._events.append((shop_id, user_id, kind, now()))

    async def flush(self) -> None:
        """Сбрасывает накопленные записи в базу одной транзакцией."""
        seen, self._seen = self._seen, {}
        screen_ids, self._screen_ids = self._screen_ids, {}
        events, self._events = self._events, []
        if seen:
            await self.db.executemany(
                "UPDATE users SET last_seen = ?, username = ?, first_name = ?, is_blocked = 0 WHERE id = ?",
                ((ts, un, fn, uid) for uid, (ts, un, fn) in seen.items()),
            )
        if screen_ids:
            await self.db.executemany(
                "UPDATE users SET screen_msg_id = ? WHERE id = ?", ((mid, uid) for uid, mid in screen_ids.items())
            )
        if events:
            await self.db.executemany("INSERT INTO events(shop_id, user_id, kind, ts) VALUES (?, ?, ?, ?)", events)

    # ---------- админы ----------
    def admin_ids(self, perm: str | None = None) -> list[int]:
        ids = set(self.config.owner_ids)
        for uid, perms in self.catalog.admins.items():
            if perm is None or perm in perms:
                ids.add(uid)
        return sorted(ids)

    def perms(self, user_id: int) -> set[str] | None:
        return self.catalog.perms_of(user_id, self.config.owner_ids)

    def has_perm(self, user_id: int, perm: str) -> bool:
        perms = self.perms(user_id)
        return perms is not None and ("*" in perms or perm in perms)

    async def notify_admins(self, html: str, perm: str | None = None, **kwargs) -> None:
        for uid in self.admin_ids(perm):
            try:
                await self.bot.send_message(uid, html, **kwargs)
            except TelegramAPIError as e:
                log.warning("Не удалось уведомить админа %s: %s", uid, e)

    async def log_action(self, admin_id: int, action: str, details: str = "", pretty: str = "") -> None:
        await self.db.execute(
            "INSERT INTO admin_log(admin_id, action, details, ts) VALUES (?, ?, ?, ?)",
            (admin_id, action, details[:500], now()),
        )
        if pretty and self.catalog.setting("log_admin_actions", 1):
            await self.log_event(f"📜 {pretty}")

    # ---------- канал логов ----------
    @property
    def log_chat(self) -> int:
        """Канал для логов, ошибок и бэкапов (0 — не задан)."""
        return int(self.catalog.setting("log_chat_id", 0) or self.catalog.setting("backup_chat_id", 0) or 0)

    async def log_event(self, html: str, **kwargs) -> bool:
        chat = self.log_chat
        if not chat:
            return False
        try:
            await self.bot.send_message(chat, html[:4000], disable_notification=True, **kwargs)
            return True
        except TelegramAPIError as e:
            log.warning("Канал логов недоступен: %s", e)
            return False
