"""Админка: статистика, защита, настройки, бэкапы, журнал, обслуживание медиа."""
import json
import tempfile
from html import escape
from pathlib import Path

from aiogram.types import Message

from ...backup import restore_backup
from ...catalog import now
from ...jobs import send_backup
from ...media import TELEGRAM_DOWNLOAD_LIMIT
from .core import Ctx, InputError, Rows, ViewResult, action, b, back_btn, on_input, view
from .shops import fmt_date

# ключ -> (название, минимум, максимум)
PROTECTION = {
    "flood_limit": ("Действий за окно (0 — выкл.)", 0, 100),
    "flood_window": ("Окно антифлуда, сек", 1, 60),
    "flood_strikes": ("Нарушений до автобана (0 — без бана)", 0, 100),
    "flood_ban_minutes": ("Автобан, минут", 0, 100000),
    "report_cooldown_minutes": ("Пауза между жалобами, минут", 0, 10000),
}
SETTINGS = {
    "per_row": ("Кнопок в ряду (списки)", 1, 4),
    "page_size": ("Кнопок на странице", 2, 50),
    "max_media_mb": ("Лимит медиа, МБ", 1, 20),
    "tz_offset": ("Часовой пояс, UTC+", -12, 14),
    "backup_hour": ("Час автобэкапа", 0, 23),
    "backup_chat_id": ("Чат для бэкапов (0 — владельцам)", -10 ** 15, 10 ** 15),
    "expiry_notify_hours": ("Напомнить о сроке метки за, ч", 1, 720),
}
ALL_SETTINGS = {**PROTECTION, **SETTINGS}


def settings_rows(ctx: Ctx, keys: dict, back: str) -> Rows:
    s = ctx.app.catalog.setting
    rows: Rows = [[b(f"{title}: {s(key)}", f"x:setv:{key}:{back}")] for key, (title, _, _) in keys.items()]
    return rows


@view("prot", "settings")
async def view_protection(ctx: Ctx) -> ViewResult:
    s = ctx.app.catalog.setting
    rows = settings_rows(ctx, PROTECTION, "prot")
    rows.append([b(f"🧹 Удалять сообщения пользователей: {'да' if s('clean_chat', 1) else 'нет'}", "x:settog:clean_chat:prot")])
    rows.append(back_btn("a:home"))
    html = ("🛡 <b>Защита</b>\n\n"
            f"Антифлуд: больше <b>{s('flood_limit')}</b> нажатий за <b>{s('flood_window')}</b> сек — "
            "бот отвечает «слишком быстро».\n"
            f"После <b>{s('flood_strikes')}</b> таких нарушений подряд — автобан на <b>{s('flood_ban_minutes')}</b> мин.\n"
            "Забаненные и флудеры отсекаются до основной логики и не нагружают бота.\n\n"
            "Удаление сообщений: всё, что пользователь пишет вне поиска и жалоб, удаляется — в чате остаётся "
            "только экран бота.")
    return html, rows


@view("set", "settings")
async def view_settings(ctx: Ctx) -> ViewResult:
    app = ctx.app
    rows = settings_rows(ctx, SETTINGS, "set")
    rows.append([b(f"🔥 Прогреть медиа ({len(app.media.pending_warmup())} без file_id)", "x:warm"),
                 b("🧹 Удалить лишние медиа", "x:gc")])
    rows.append(back_btn("a:home"))
    total = sum(m.size for m in app.media.files.values()) / 1048576
    html = ("⚙️ <b>Настройки</b>\n\n"
            f"Медиафайлов: <b>{len(app.media.files)}</b> ({total:.1f} МБ)\n"
            "«Прогреть» — заранее загрузить все медиа в Telegram (нужно после смены токена; "
            "делается и автоматически при запуске).")
    return html, rows


@action("setv", "settings")
async def act_setting_value(ctx: Ctx, key: str, back: str):
    title, lo, hi = ALL_SETTINGS[key]
    return await ctx.ask("setv", f"<b>{title}</b>\nОтправьте число от {lo} до {hi}.", f"a:{back}", key, back)


@on_input("setv", "settings")
async def in_setting_value(ctx: Ctx, message: Message, key: str, back: str):
    title, lo, hi = ALL_SETTINGS[key]
    try:
        value = int((message.text or "").strip())
    except ValueError:
        raise InputError("Нужно целое число.")
    if not lo <= value <= hi:
        raise InputError(f"Число должно быть от {lo} до {hi}.")
    await ctx.app.db.execute("INSERT OR REPLACE INTO settings(key, value) VALUES (?, ?)", (key, json.dumps(value)))
    await ctx.reload()
    await ctx.log("settings", f"{key}={value}")
    ctx.notice = "✅ Сохранено"
    return f"a:{back}"


@action("settog", "settings")
async def act_setting_toggle(ctx: Ctx, key: str, back: str):
    value = 0 if ctx.app.catalog.setting(key, 0) else 1
    await ctx.app.db.execute("INSERT OR REPLACE INTO settings(key, value) VALUES (?, ?)", (key, json.dumps(value)))
    await ctx.reload()
    return f"a:{back}"


@action("warm", "settings")
async def act_warmup(ctx: Ctx):
    await ctx.toast("Загружаю медиа, это может занять время…")
    ok, failed = await ctx.app.media.warmup(ctx.app.bot, ctx.chat_id)
    ctx.notice = f"🔥 Загружено: {ok}, ошибок: {failed}"
    return "a:set"


@action("gc", "settings")
async def act_media_gc(ctx: Ctx):
    removed = await ctx.app.media.collect_garbage()
    ctx.notice = f"🧹 Удалено неиспользуемых файлов: {removed}"
    return "a:set"


# ---------- статистика ----------
@view("stats", "stats")
async def view_stats(ctx: Ctx) -> ViewResult:
    app = ctx.app
    await app.flush()
    db, cat, t = app.db, app.catalog, now()

    async def count(sql: str, *params) -> int:
        return await db.fetchval(sql, params) or 0

    views = [await count("SELECT COUNT(*) FROM events WHERE ts > ?", t - d * 86400) for d in (1, 7, 30)]
    uniq = await count("SELECT COUNT(DISTINCT user_id) FROM events WHERE ts > ?", t - 7 * 86400)
    top = await db.fetchall(
        "SELECT shop_id, COUNT(*) AS n FROM events WHERE ts > ? GROUP BY shop_id ORDER BY n DESC LIMIT 10",
        (t - 30 * 86400,))
    top_lines = "\n".join(
        f"{i}. {escape(cat.shops[r['shop_id']].label) if r['shop_id'] in cat.shops else '#' + str(r['shop_id'])} — {r['n']}"
        for i, r in enumerate(top, 1)) or "пока нет данных"
    tags = "\n".join(f"• {escape(tg.label)}: {len(cat.by_tag.get(tg.id, []))}" for tg in cat.tags.values())
    html = (
        "📊 <b>Статистика</b>\n\n"
        f"Пользователей: <b>{await count('SELECT COUNT(*) FROM users')}</b>, "
        f"активны за сутки: <b>{await count('SELECT COUNT(*) FROM users WHERE last_seen > ?', t - 86400)}</b>\n"
        f"Магазинов: <b>{len(cat.all_shops)}</b> опубликовано, {len(cat.shops) - len(cat.all_shops)} скрыто\n{tags}\n\n"
        f"Просмотры карточек: сутки <b>{views[0]}</b> · 7 дн <b>{views[1]}</b> · 30 дн <b>{views[2]}</b>\n"
        f"Уникальных зрителей за 7 дн: <b>{uniq}</b>\n\n"
        f"<b>Топ магазинов за 30 дней:</b>\n{top_lines}"
    )
    return html, [back_btn("a:home")]


# ---------- бэкап ----------
@view("bak", "backup")
async def view_backup(ctx: Ctx) -> ViewResult:
    cat = ctx.app.catalog
    html = ("💾 <b>Бэкап</b>\n\n"
            "Архив = база (все тексты, кнопки, магазины, пользователи) + все медиафайлы.\n"
            f"Автоматически — каждый день в {cat.setting('backup_hour')}:00 "
            f"(UTC+{cat.setting('tz_offset')}), последний: {cat.setting('last_backup_day', '—')}.\n\n"
            "<b>Переезд на новый токен:</b> меняете BOT_TOKEN в .env и перезапускаете — всё на месте, медиа "
            "перезальются сами.\n"
            "<b>Переезд на новый сервер:</b> копируете папку data целиком, либо восстанавливаете из архива.")
    rows = [[b("💾 Сделать бэкап сейчас", "x:bakgo", "success")],
            [b("♻️ Восстановить из архива", "x:bakrest", "danger")],
            back_btn("a:home")]
    return html, rows


@action("bakgo", "backup")
async def act_backup_now(ctx: Ctx):
    await ctx.toast("Собираю архив…")
    note = await send_backup(ctx.app, ctx.chat_id, "💾 Бэкап")
    await ctx.log("backup.create")
    ctx.notice = "✅ Бэкап отправлен ниже." + note
    return "a:bak"


@action("bakrest", "backup")
async def act_backup_restore(ctx: Ctx):
    return await ctx.ask(
        "bakrest",
        "⚠️ Текущие данные будут <b>заменены</b> данными из архива (копия текущей базы сохранится на сервере).\n\n"
        f"Пришлите zip-архив бэкапа файлом (до {TELEGRAM_DOWNLOAD_LIMIT // 1048576} МБ — лимит Telegram).\n"
        "Архив больше — восстановите на сервере: <code>python -m bot.restore архив.zip</code>",
        "a:bak",
    )


@on_input("bakrest", "backup")
async def in_backup_restore(ctx: Ctx, message: Message):
    doc = message.document
    if doc is None or not (doc.file_name or "").endswith(".zip"):
        raise InputError("Нужен zip-файл бэкапа.")
    if (doc.file_size or 0) > TELEGRAM_DOWNLOAD_LIMIT:
        raise InputError("Архив больше 20 МБ — восстановите на сервере командой python -m bot.restore.")
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "restore.zip"
        await ctx.app.bot.download(doc.file_id, destination=path)
        try:
            await restore_backup(ctx.app, path)
        except (ValueError, OSError) as e:
            raise InputError(f"Архив не подошёл: {e}")
    await ctx.log("backup.restore", doc.file_name or "")
    ctx.notice = "✅ Данные восстановлены из архива."
    return "a:bak"


# ---------- журнал ----------
ACTION_NAMES = {
    "shop.create": "создал магазин", "shop.delete": "удалил магазин", "shop.publish": "опубликовал магазин",
    "shop.hide": "скрыл магазин", "shop.tag_on": "поставил метку", "shop.tag_off": "снял метку",
    "shop.tag_expired": "срок метки истёк", "shop.tag_expiry": "срок метки", "shop.contacts": "контакты",
    "shop.verified": "«Проверенный»", "user.ban": "бан", "user.unban": "разбан", "admin.add": "добавил админа",
    "admin.remove": "снял админа", "admin.perms": "права админа", "broadcast.start": "рассылка",
    "backup.create": "бэкап", "backup.restore": "восстановление", "settings": "настройка",
}


@view("log", "log")
async def view_log(ctx: Ctx, page: str = "0") -> ViewResult:
    p = max(0, int(page))
    size = 20
    rows_db = await ctx.app.db.fetchall(
        "SELECT * FROM admin_log ORDER BY id DESC LIMIT ? OFFSET ?", (size + 1, p * size))
    tz = int(ctx.app.catalog.setting("tz_offset", 5))
    lines = [
        f"<code>{fmt_date(r['ts'], tz)}</code> "
        f"{'🤖' if r['admin_id'] == 0 else r['admin_id']}: {ACTION_NAMES.get(r['action'], r['action'])} "
        f"{escape(r['details'][:60])}"
        for r in rows_db[:size]
    ]
    nav = []
    if p > 0:
        nav.append(b("◀️ Новее", f"a:log:{p - 1}"))
    if len(rows_db) > size:
        nav.append(b("Старее ▶️", f"a:log:{p + 1}"))
    return "📜 <b>Журнал действий</b>\n\n" + ("\n".join(lines) or "пусто"), [nav, back_btn("a:home")]

