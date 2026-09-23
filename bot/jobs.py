"""Фоновые задачи: сброс буферов, сроки меток, истёкшие баны, ежедневный бэкап."""
import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from html import escape

from aiogram.exceptions import TelegramAPIError
from aiogram.types import FSInputFile

from .app import App
from .backup import make_backup
from .catalog import now
from .middlewares import GuardMiddleware

log = logging.getLogger(__name__)

FLUSH_EVERY = 30
MAINTENANCE_EVERY = 300
EVENTS_KEEP_DAYS = 180
LOG_KEEP_DAYS = 90  # журнал действий админов
SEND_LIMIT = 49 * 1024 * 1024  # бот может отправить файл до 50 МБ


async def run_jobs(app: App, guard: GuardMiddleware) -> None:
    ticks = 0
    while True:
        await asyncio.sleep(FLUSH_EVERY)
        ticks += FLUSH_EVERY
        try:
            await app.flush()
            if ticks % MAINTENANCE_EVERY == 0:
                guard.cleanup()
                await check_tag_expiry(app)
                await expire_bans(app)
                await daily_backup(app)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Ошибка фоновой задачи")


async def check_tag_expiry(app: App) -> None:
    db, cat = app.db, app.catalog
    t = now()
    hours = int(cat.setting("expiry_notify_hours", 24))
    soon = await db.fetchall(
        "SELECT st.shop_id, st.tag_id, st.expires_at, s.label AS shop, g.label AS tag FROM shop_tags st "
        "JOIN shops s ON s.id = st.shop_id JOIN tags g ON g.id = st.tag_id "
        "WHERE st.expires_at IS NOT NULL AND st.notified = 0 AND st.expires_at > ? AND st.expires_at <= ?",
        (t, t + hours * 3600),
    )
    for r in soon:
        left = max(1, (r["expires_at"] - t) // 3600)
        msg = f"⏳ У магазина <b>{escape(r['shop'])}</b> через {left} ч закончится метка <b>{escape(r['tag'])}</b>."
        await app.notify_admins(msg, perm="shops")
        await app.log_event(msg)
        await db.execute("UPDATE shop_tags SET notified = 1 WHERE shop_id = ? AND tag_id = ?", (r["shop_id"], r["tag_id"]))

    expired = await db.fetchall(
        "SELECT st.shop_id, st.tag_id, s.label AS shop, g.label AS tag FROM shop_tags st "
        "JOIN shops s ON s.id = st.shop_id JOIN tags g ON g.id = st.tag_id "
        "WHERE st.expires_at IS NOT NULL AND st.expires_at <= ?",
        (t,),
    )
    if not expired:
        return
    await db.execute("DELETE FROM shop_tags WHERE expires_at IS NOT NULL AND expires_at <= ?", (t,))
    await cat.reload()
    for r in expired:
        await app.log_action(0, "shop.tag_expired", f"{r['shop_id']}/{r['tag_id']}")
        msg = f"⌛️ Срок истёк: у магазина <b>{escape(r['shop'])}</b> снята метка <b>{escape(r['tag'])}</b>."
        await app.notify_admins(msg, perm="shops")
        await app.log_event(msg)


async def expire_bans(app: App) -> None:
    t = now()
    for uid in [u for u, until in app.banned.items() if until is not None and until <= t]:
        await app.unban(uid)


async def daily_backup(app: App) -> None:
    cat = app.catalog
    tz = timezone(timedelta(hours=int(cat.setting("tz_offset", 5))))
    local = datetime.now(tz)
    today = local.strftime("%Y-%m-%d")
    if local.hour < int(cat.setting("backup_hour", 4)) or cat.setting("last_backup_day", "") == today:
        return
    await app.db.execute("INSERT OR REPLACE INTO settings(key, value) VALUES ('last_backup_day', ?)", (json.dumps(today),))
    cat.settings["last_backup_day"] = today
    await app.db.execute("DELETE FROM events WHERE ts < ?", (now() - EVENTS_KEEP_DAYS * 86400,))
    await app.db.execute("DELETE FROM admin_log WHERE ts < ?", (now() - LOG_KEEP_DAYS * 86400,))
    await send_backup(app, None, caption="💾 Ежедневный бэкап")
    removed = await app.media.collect_garbage()  # картинки, которые уже нигде не стоят (они есть в бэкапе)
    if removed:
        log.info("Удалено неиспользуемых медиа: %s", removed)


async def send_backup(app: App, chat_id: int | None, caption: str) -> str:
    """Делает бэкап и отправляет его. chat_id=None — в канал из настроек или владельцам."""
    path = await make_backup(app)
    note = ""
    if path.stat().st_size > SEND_LIMIT:
        path = await make_backup(app, with_media=False)
        note = "\n⚠️ Медиа не поместились в лимит Telegram (50 МБ), поэтому отправлена только база. Полный архив лежит на сервере в data/backups."
    targets = [chat_id] if chat_id else ([app.log_chat] if app.log_chat else sorted(app.config.owner_ids))
    for target in targets:
        try:
            await app.bot.send_document(target, FSInputFile(path), caption=caption + note, disable_notification=True)
        except TelegramAPIError as e:
            log.warning("Не удалось отправить бэкап в %s: %s", target, e)
    return note
