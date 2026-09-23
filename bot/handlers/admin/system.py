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
from .journal import describe
from .shops import fmt_date

# ключ -> (название, минимум, максимум)
PROTECTION = {
    "flood_limit": ("Действий за окно (0 выключает)", 0, 100),
    "flood_window": ("Окно антифлуда, сек", 1, 60),
    "flood_strikes": ("Нарушений до автобана (0 без бана)", 0, 100),
    "flood_ban_minutes": ("Автобан, минут", 0, 100000),
    "report_cooldown_minutes": ("Пауза между жалобами, минут", 0, 10000),
    "apply_cooldown_hours": ("Пауза между заявками, часов", 0, 10000),
}
SETTINGS = {
    "per_row": ("Кнопок в ряду (списки)", 1, 4),
    "page_size": ("Кнопок на странице", 2, 50),
    "max_media_mb": ("Лимит медиа, МБ", 1, 20),
    "tz_offset": ("Часовой пояс, UTC+", -12, 14),
    "backup_hour": ("Час автобэкапа", 0, 23),
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
    rows.append([b(f"🔒 Запрет пересылки и скриншотов: {'да' if s('protect_content', 1) else 'нет'}",
                   "x:settog:protect_content:prot")])
    rows.append(back_btn("a:cfg"))
    html = ("🛡 <b>Защита</b>\n\n"
            f"Больше <b>{s('flood_limit')}</b> нажатий за <b>{s('flood_window')}</b> сек: бот просит не спешить. "
            f"После <b>{s('flood_strikes')}</b> раз бан на <b>{s('flood_ban_minutes')}</b> мин.\n"
            "Запрет пересылки на админов не действует.")
    return html, rows


@view("set", "settings")
async def view_settings(ctx: Ctx) -> ViewResult:
    app = ctx.app
    rows = settings_rows(ctx, SETTINGS, "set")
    log_chat = app.log_chat
    rows.insert(0, [b(f"📡 Канал логов и бэкапов: {log_chat or 'не задан'}", "x:logchat")])
    rows.insert(1, [b(f"📜 Действия админов в канал: "
                      f"{'да' if app.catalog.setting('log_admin_actions', 1) else 'нет'}",
                      "x:settog:log_admin_actions:set")])
    rows.append(back_btn("a:cfg"))
    html = ("⚙️ <b>Настройки</b>\n\n"
            "Канал логов: туда приходят бэкапы, заявки, жалобы и ошибки. Без него бэкапы идут владельцу в личку.")
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


@action("logchat", "settings")
async def act_log_chat(ctx: Ctx):
    return await ctx.ask(
        "logchat",
        "📡 <b>Подключение канала логов</b>\n\n"
        "1. Создайте приватный канал.\n"
        "2. Добавьте этого бота в канал администратором (с правом публиковать сообщения).\n"
        "3. Перешлите сюда любое сообщение из канала или отправьте его ID, он начинается с -100.\n\n"
        "Отправьте <code>0</code>, чтобы отключить канал.",
        "a:set",
    )


@on_input("logchat", "settings")
async def in_log_chat(ctx: Ctx, message: Message):
    chat_id = None
    origin = message.forward_origin
    if origin is not None and getattr(origin, "chat", None) is not None:
        chat_id = origin.chat.id
    elif (message.text or "").strip().lstrip("-").isdigit():
        chat_id = int(message.text.strip())
    if chat_id is None:
        raise InputError("Перешлите сообщение из канала или отправьте его ID.")
    if chat_id:
        try:
            await ctx.app.bot.send_message(chat_id, "✅ Канал подключён: сюда будут приходить логи, ошибки и бэкапы.")
        except Exception as e:
            raise InputError(f"Бот не может писать в этот канал ({e}). Добавьте бота администратором.")
    await ctx.app.db.execute("INSERT OR REPLACE INTO settings(key, value) VALUES ('log_chat_id', ?)", (str(chat_id),))
    await ctx.app.db.execute("INSERT OR REPLACE INTO settings(key, value) VALUES ('backup_chat_id', '0')")
    await ctx.reload()
    await ctx.log("logchat.set", str(chat_id))
    ctx.notice = "✅ Канал логов подключён." if chat_id else "Канал логов отключён."
    return "a:set"


# ---------- статистика ----------
@view("stats", "stats")
async def view_stats(ctx: Ctx) -> ViewResult:
    app = ctx.app
    await app.flush()
    db, cat, t = app.db, app.catalog, now()

    async def count(sql: str, *params) -> int:
        return await db.fetchval(sql, params) or 0

    day, week, month = t - 86400, t - 7 * 86400, t - 30 * 86400
    views = [await count("SELECT COUNT(*) FROM events WHERE ts > ?", since) for since in (day, week, month)]
    seen = [await count("SELECT COUNT(*) FROM users WHERE last_seen > ?", since) for since in (day, week, month)]
    uniq = await count("SELECT COUNT(DISTINCT user_id) FROM events WHERE ts > ?", week)
    top = await db.fetchall(
        "SELECT shop_id, COUNT(*) AS n FROM events WHERE ts > ? GROUP BY shop_id ORDER BY n DESC LIMIT 10", (month,))
    medals = {1: "🥇", 2: "🥈", 3: "🥉"}
    top_lines = "\n".join(
        f"{medals.get(i, f'{i}.')} {escape(cat.shops[r['shop_id']].label) if r['shop_id'] in cat.shops else '#' + str(r['shop_id'])}"
        f" · <b>{r['n']}</b>"
        for i, r in enumerate(top, 1)) or "пока нет просмотров"
    tags = " · ".join(f"{escape(tg.label)}: <b>{len(cat.by_tag.get(tg.id, []))}</b>" for tg in cat.tags.values())
    html = (
        "📊 <b>Статистика</b>\n\n"
        "👥 <b>Пользователи</b>\n"
        f"Всего <b>{await count('SELECT COUNT(*) FROM users')}</b>, "
        f"новых за неделю <b>{await count('SELECT COUNT(*) FROM users WHERE created_at > ?', week)}</b>\n"
        f"Заходили: сутки <b>{seen[0]}</b> · неделя <b>{seen[1]}</b> · месяц <b>{seen[2]}</b>\n\n"
        "🏪 <b>Магазины</b>\n"
        f"Опубликовано <b>{len(cat.all_shops)}</b>, скрыто <b>{len(cat.shops) - len(cat.all_shops)}</b>\n"
        + (f"{tags}\n" if tags else "") + "\n"
        "👁 <b>Открыли карточки</b>\n"
        f"Сутки <b>{views[0]}</b> · неделя <b>{views[1]}</b> · месяц <b>{views[2]}</b>\n"
        f"Разных людей за неделю: <b>{uniq}</b>\n\n"
        f"🏆 <b>Популярные за месяц</b>\n{top_lines}"
    )
    return html, [back_btn("a:home")]


# ---------- бэкап ----------
@view("bak", "backup")
async def view_backup(ctx: Ctx) -> ViewResult:
    cat = ctx.app.catalog
    html = ("💾 <b>Бэкап</b>\n\n"
            "Архив = база (все тексты, кнопки, магазины, пользователи) + все медиафайлы.\n"
            f"Автоматически каждый день в {cat.setting('backup_hour')}:00 "
            f"(UTC+{cat.setting('tz_offset')}). Последний: {cat.setting('last_backup_day', 'ещё не было')}.\n"
            f"Куда: {'в канал логов' if ctx.app.log_chat else 'владельцам в личку (подключите канал в ⚙️ Настройках)'}.\n\n"
            "<b>Переезд на новый токен:</b> меняете BOT_TOKEN в .env и перезапускаете. Всё остаётся на месте, медиа "
            "перезальются сами.\n"
            "<b>Переезд на новый сервер:</b> копируете папку data целиком, либо восстанавливаете из архива.")
    rows = [[b("💾 Сделать бэкап сейчас", "x:bakgo", "success")],
            [b("♻️ Восстановить из архива", "x:bakrest", "danger")],
            back_btn("a:cfg")]
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
        f"Пришлите zip-архив бэкапа файлом, до {TELEGRAM_DOWNLOAD_LIMIT // 1048576} МБ (лимит Telegram).\n"
        "Если архив больше, восстановите его на сервере: <code>python -m bot.restore архив.zip</code>",
        "a:bak",
    )


@on_input("bakrest", "backup")
async def in_backup_restore(ctx: Ctx, message: Message):
    doc = message.document
    if doc is None or not (doc.file_name or "").endswith(".zip"):
        raise InputError("Нужен zip-файл бэкапа.")
    if (doc.file_size or 0) > TELEGRAM_DOWNLOAD_LIMIT:
        raise InputError("Архив больше 20 МБ. Восстановите его на сервере командой python -m bot.restore.")
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
@view("log", "log")
async def view_log(ctx: Ctx, page: str = "0") -> ViewResult:
    p = max(0, int(page))
    size = 20
    rows_db = await ctx.app.db.fetchall(
        "SELECT * FROM admin_log ORDER BY id DESC LIMIT ? OFFSET ?", (size + 1, p * size))
    tz = int(ctx.app.catalog.setting("tz_offset", 5))
    names = {r["id"]: r["first_name"] for r in await ctx.app.db.fetchall(
        "SELECT id, first_name FROM users WHERE id IN (SELECT DISTINCT admin_id FROM admin_log)")}
    lines = [
        f"<code>{fmt_date(r['ts'], tz)}</code> "
        f"{'🤖 бот' if r['admin_id'] == 0 else escape(names.get(r['admin_id']) or str(r['admin_id']))}: "
        f"{describe(ctx.app, r['action'], r['details'])}"
        for r in rows_db[:size]
    ]
    nav = []
    if p > 0:
        nav.append(b("◀️ Новее", f"a:log:{p - 1}"))
    if len(rows_db) > size:
        nav.append(b("Старее ▶️", f"a:log:{p + 1}"))
    return "📜 <b>Журнал</b>, хранится 90 дней\n\n" + ("\n".join(lines) or "пусто"), [nav, back_btn("a:cfg")]

