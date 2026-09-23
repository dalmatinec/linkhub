"""Админка: пользователи и баны, админы и права, рассылка, жалобы."""
import asyncio
import logging
from html import escape

from aiogram.exceptions import TelegramAPIError, TelegramForbiddenError, TelegramRetryAfter
from aiogram.types import Message

from ...app import App
from ...catalog import now
from ...ui import button, grid, paginate
from .core import PERMS, Ctx, InputError, Rows, ViewResult, action, b, back_btn, on_input, view
from .shops import fmt_date

log = logging.getLogger(__name__)


# ---------- пользователи ----------
@view("users", "users")
async def view_users(ctx: Ctx) -> ViewResult:
    db = ctx.app.db
    t = now()
    total = await db.fetchval("SELECT COUNT(*) FROM users")
    day = await db.fetchval("SELECT COUNT(*) FROM users WHERE last_seen > ?", (t - 86400,))
    new_day = await db.fetchval("SELECT COUNT(*) FROM users WHERE created_at > ?", (t - 86400,))
    new_week = await db.fetchval("SELECT COUNT(*) FROM users WHERE created_at > ?", (t - 7 * 86400,))
    banned = await db.fetchval("SELECT COUNT(*) FROM users WHERE is_banned = 1")
    blocked = await db.fetchval("SELECT COUNT(*) FROM users WHERE is_blocked = 1")
    html = (f"👥 <b>Пользователи</b>\n\n"
            f"Всего: <b>{total}</b>\n"
            f"Активны за сутки: <b>{day}</b>\n"
            f"Новых за сутки / 7 дней: <b>{new_day}</b> / <b>{new_week}</b>\n"
            f"Забанены: <b>{banned}</b>\n"
            f"Заблокировали бота: <b>{blocked}</b>")
    rows = [[b("🔍 Найти пользователя", "x:ufind")], [b("🚫 Забаненные", "a:banned:0")], back_btn("a:home")]
    return html, rows


@action("ufind", "users")
async def act_user_find(ctx: Ctx):
    return await ctx.ask("ufind", "Отправьте ID пользователя, @username или перешлите его сообщение.", "a:users")


@on_input("ufind", "users")
async def in_user_find(ctx: Ctx, message: Message):
    uid = None
    origin = message.forward_origin
    if origin is not None:
        sender = getattr(origin, "sender_user", None)
        if sender is None:
            raise InputError("Пользователь скрыл пересылку — пришлите его ID.")
        uid = sender.id
    text = (message.text or "").strip()
    if uid is None and text.lstrip("-").isdigit():
        uid = int(text)
    elif uid is None and text:
        uid = await ctx.app.db.fetchval("SELECT id FROM users WHERE username = ? COLLATE NOCASE", (text.lstrip("@"),))
    if uid is None:
        raise InputError("Пользователь не найден (он должен хотя бы раз запустить бота).")
    return f"a:user:{uid}"


@view("user", "users")
async def view_user(ctx: Ctx, user_id: str) -> ViewResult:
    app = ctx.app
    uid = int(user_id)
    row = await app.db.fetchone("SELECT * FROM users WHERE id = ?", (uid,))
    tz = int(app.catalog.setting("tz_offset", 5))
    if row is None:
        html = f"👤 <code>{uid}</code>\nВ базе нет — бот его ещё не видел."
    else:
        ban = "нет"
        if row["is_banned"]:
            ban = "навсегда" if row["banned_until"] is None else f"до {fmt_date(row['banned_until'], tz)}"
            if row["ban_reason"]:
                ban += f" ({escape(row['ban_reason'])})"
        html = (f"👤 <b>{escape(row['first_name'] or '—')}</b> "
                f"{'@' + escape(row['username']) if row['username'] else ''}\n"
                f"ID: <code>{uid}</code>\n"
                f"Первый вход: {fmt_date(row['created_at'], tz)}\n"
                f"Последняя активность: {fmt_date(row['last_seen'], tz)}\n"
                f"Бан: {ban}\n"
                f"Заблокировал бота: {'да' if row['is_blocked'] else 'нет'}")
    rows: Rows = []
    if uid in app.config.owner_ids:
        html += "\n\n👑 Владелец — забанить нельзя."
    elif app.is_banned(uid):
        rows.append([b("✅ Разбанить", f"x:unban:{uid}", "success")])
    else:
        rows.append([b("⏳ 1 час", f"x:ban:{uid}:60"), b("⏳ 1 день", f"x:ban:{uid}:1440"),
                     b("⏳ 7 дней", f"x:ban:{uid}:10080")])
        rows.append([b("🚫 Навсегда", f"x:ban:{uid}:0", "danger")])
    rows.append(back_btn("a:users"))
    return html, rows


@action("ban", "users")
async def act_ban(ctx: Ctx, user_id: str, minutes: str):
    uid = int(user_id)
    if uid in ctx.app.config.owner_ids or ctx.app.perms(uid) is not None:
        ctx.notice = "⛔️ Админа забанить нельзя — сначала снимите права."
        return f"a:user:{uid}"
    until = None if minutes == "0" else now() + int(minutes) * 60
    await ctx.app.ban(uid, until, f"админ {ctx.user_id}")
    await ctx.log("user.ban", f"{uid} на {minutes or '∞'} мин")
    return f"a:user:{uid}"


@action("unban", "users")
async def act_unban(ctx: Ctx, user_id: str):
    await ctx.app.unban(int(user_id))
    await ctx.log("user.unban", user_id)
    return f"a:user:{user_id}"


@view("banned", "users")
async def view_banned(ctx: Ctx, page: str = "0") -> ViewResult:
    rows_db = await ctx.app.db.fetchall(
        "SELECT id, first_name, username FROM users WHERE is_banned = 1 ORDER BY id")
    chunk, p, pages = paginate(rows_db, int(page), 30)
    rows = grid([b(f"{r['first_name'] or r['id']}", f"a:user:{r['id']}") for r in chunk], 2)
    nav = []
    if p > 0:
        nav.append(b("◀️", f"a:banned:{p - 1}"))
    if pages > 1:
        nav.append(button(f"{p + 1}/{pages}", cb="noop"))
    if p < pages - 1:
        nav.append(b("▶️", f"a:banned:{p + 1}"))
    rows.append(nav)
    rows.append(back_btn("a:users"))
    return f"🚫 <b>Забаненные</b> — {len(rows_db)}", rows


# ---------- админы ----------
@view("admins", "admins")
async def view_admins(ctx: Ctx) -> ViewResult:
    app = ctx.app
    rows: Rows = [[button(f"👑 {uid}", cb="noop")] for uid in sorted(app.config.owner_ids)]
    names = {r["id"]: r["first_name"] for r in await app.db.fetchall("SELECT id, first_name FROM users WHERE id IN "
                                                                       "(SELECT user_id FROM admins)")}
    for uid, perms in app.catalog.admins.items():
        rows.append([b(f"👮 {names.get(uid) or uid} · прав: {len(perms)}", f"a:adm:{uid}")])
    rows.append([b("➕ Добавить админа", "x:adnew", "success")])
    rows.append(back_btn("a:home"))
    html = ("👮 <b>Админы</b>\n\n👑 — владельцы из .env, у них все права.\n"
            "Остальным права выдаются галочками по разделам.")
    return html, rows


@action("adnew", "admins")
async def act_admin_new(ctx: Ctx):
    return await ctx.ask("adnew", "Отправьте ID будущего админа или перешлите его сообщение.", "a:admins")


@on_input("adnew", "admins")
async def in_admin_new(ctx: Ctx, message: Message):
    uid = None
    if message.forward_origin is not None:
        sender = getattr(message.forward_origin, "sender_user", None)
        uid = sender.id if sender else None
    elif (message.text or "").strip().isdigit():
        uid = int(message.text.strip())
    if uid is None:
        raise InputError("Нужен числовой ID (пересылка скрыта настройками приватности).")
    await ctx.app.db.execute("INSERT OR IGNORE INTO admins(user_id, perms, added_by, created_at) VALUES (?, 'shops', ?, ?)",
                             (uid, ctx.user_id, now()))
    await ctx.reload()
    await ctx.log("admin.add", str(uid))
    ctx.notice = "✅ Админ добавлен с правом «Магазины». Отметьте нужные разделы."
    return f"a:adm:{uid}"


@view("adm", "admins")
async def view_admin(ctx: Ctx, user_id: str) -> ViewResult:
    perms = ctx.app.catalog.admins.get(int(user_id))
    if perms is None:
        return await view_admins(ctx)
    rows = grid([b(f"{'✅' if key in perms else '▫️'} {title}", f"x:adp:{user_id}:{key}") for key, title in PERMS.items()], 2)
    rows.append([b("🗑 Снять с админов", f"x:addel:{user_id}", "danger")])
    rows.append(back_btn("a:admins"))
    return f"👮 <b>Права админа</b> <code>{user_id}</code>\nАдминка открывается командой /admin", rows


@action("adp", "admins")
async def act_admin_perm(ctx: Ctx, user_id: str, perm: str):
    perms = set(ctx.app.catalog.admins.get(int(user_id), set()))
    perms.symmetric_difference_update({perm})
    await ctx.app.db.execute("UPDATE admins SET perms = ? WHERE user_id = ?", (",".join(sorted(perms)), int(user_id)))
    await ctx.reload()
    await ctx.log("admin.perms", f"{user_id}: {','.join(sorted(perms))}")
    return f"a:adm:{user_id}"


@action("addel", "admins")
async def act_admin_delete(ctx: Ctx, user_id: str):
    await ctx.app.db.execute("DELETE FROM admins WHERE user_id = ?", (int(user_id),))
    await ctx.reload()
    await ctx.log("admin.remove", user_id)
    return "a:admins"


# ---------- рассылка ----------
broadcast_task: asyncio.Task | None = None


@view("bc", "broadcast")
async def view_broadcast(ctx: Ctx) -> ViewResult:
    running = broadcast_task is not None and not broadcast_task.done()
    count = await ctx.app.db.fetchval("SELECT COUNT(*) FROM users WHERE is_blocked = 0 AND is_banned = 0")
    html = (f"📣 <b>Рассылка</b>\n\nПолучателей: <b>{count}</b>\n"
            "Можно отправить любое сообщение: текст с премиум-эмодзи, фото, GIF, видео.\n"
            + ("\n⏳ Сейчас идёт рассылка." if running else ""))
    rows: Rows = [] if running else [[b("✍️ Создать рассылку", "x:bcnew")]]
    rows.append(back_btn("a:home"))
    return html, rows


@action("bcnew", "broadcast")
async def act_broadcast_new(ctx: Ctx):
    return await ctx.ask("bcnew", "Отправьте сообщение для рассылки — ровно так оно и уйдёт пользователям.", "a:bc",
                         keep_message=True)


@on_input("bcnew", "broadcast")
async def in_broadcast(ctx: Ctx, message: Message) -> ViewResult:
    return await view_broadcast_confirm(ctx, str(message.message_id), "copy", "all")


MODES = {"copy": "📨 Копией (от имени бота)", "fwd": "↪️ Пересылкой (с автором/каналом)"}


async def _audience(app: App, lang: str) -> list[int]:
    rows = await app.db.fetchall("SELECT id, lang FROM users WHERE is_blocked = 0 AND is_banned = 0")
    if lang == "all":
        return [r["id"] for r in rows]
    # язык пользователя: выбранный вручную, иначе основной
    return [r["id"] for r in rows if app.catalog.pick_lang(r["lang"], None) == lang]


@view("bcc", "broadcast")
async def view_broadcast_confirm(ctx: Ctx, message_id: str, mode: str, lang: str) -> ViewResult:
    app = ctx.app
    count = len(await _audience(app, lang))
    langs = {"all": "👥 Всем", **app.catalog.languages}
    html = (f"☝️ Сообщение выше получат <b>{count}</b> пользователей.\n\n"
            f"Способ: <b>{MODES[mode]}</b>\n"
            "• Копией — придёт как сообщение бота, без подписи «Переслано».\n"
            "• Пересылкой — с подписью «Переслано от …». Удобно, если вы переслали боту пост своего канала: "
            "у людей будет видно канал и на него можно нажать.\n\n"
            f"Кому: <b>{langs.get(lang, lang)}</b>")
    rows: Rows = [
        [b(("• " if m == mode else "") + t.split(" (")[0], f"a:bcc:{message_id}:{m}:{lang}") for m, t in MODES.items()],
        [b(("• " if code == lang else "") + name, f"a:bcc:{message_id}:{mode}:{code}") for code, name in langs.items()],
        [b("✅ Отправить", f"x:bcgo:{message_id}:{mode}:{lang}", "success"), b("✖️ Отмена", "a:bc")],
    ]
    return html, rows


@action("bcgo", "broadcast")
async def act_broadcast_go(ctx: Ctx, message_id: str, mode: str = "copy", lang: str = "all"):
    global broadcast_task
    if broadcast_task is not None and not broadcast_task.done():
        return "a:bc"
    ids = await _audience(ctx.app, lang)
    broadcast_task = asyncio.create_task(
        run_broadcast(ctx.app, ctx.user_id, ctx.chat_id, int(message_id), ids, forward=mode == "fwd"))
    await ctx.log("broadcast.start", f"{len(ids)} получателей, {MODES.get(mode, mode)}")
    ctx.notice = "🚀 Рассылка запущена. Пришлю отчёт, когда закончится."
    return "a:bc"


async def run_broadcast(app: App, admin_id: int, from_chat: int, message_id: int, ids: list[int],
                        forward: bool = False) -> None:
    ok = blocked = failed = 0
    send = app.bot.forward_message if forward else app.bot.copy_message
    protect = bool(app.catalog.setting("protect_content", 1))
    for uid in ids:
        while True:
            try:
                await send(uid, from_chat, message_id, protect_content=protect and app.perms(uid) is None)
                ok += 1
            except TelegramRetryAfter as e:
                await asyncio.sleep(e.retry_after + 1)
                continue
            except TelegramForbiddenError:
                blocked += 1
                await app.db.execute("UPDATE users SET is_blocked = 1 WHERE id = ?", (uid,))
            except TelegramAPIError:
                failed += 1
            break
        await asyncio.sleep(0.05)  # ~20 сообщений в секунду — в пределах лимитов Telegram
    report = (f"📣 Рассылка завершена\n✅ Доставлено: {ok}\n"
              f"🚫 Заблокировали бота: {blocked}\n⚠️ Ошибки: {failed}")
    try:
        await app.bot.send_message(admin_id, report)
    except TelegramAPIError:
        log.warning("Не удалось отправить отчёт о рассылке")
    await app.log_event(report)


# ---------- жалобы ----------
@view("reps", "reports")
async def view_reports(ctx: Ctx, page: str = "0") -> ViewResult:
    rows_db = await ctx.app.db.fetchall(
        "SELECT r.id, r.text, s.label FROM reports r JOIN shops s ON s.id = r.shop_id "
        "WHERE r.status = 'open' ORDER BY r.created_at DESC")
    chunk, p, pages = paginate(rows_db, int(page), 15)
    rows: Rows = [[b(f"#{r['id']} {r['label']}: {r['text'][:30]}", f"a:rep:{r['id']}")] for r in chunk]
    nav = []
    if p > 0:
        nav.append(b("◀️", f"a:reps:{p - 1}"))
    if pages > 1:
        nav.append(button(f"{p + 1}/{pages}", cb="noop"))
    if p < pages - 1:
        nav.append(b("▶️", f"a:reps:{p + 1}"))
    rows.append(nav)
    rows.append(back_btn("a:home"))
    return f"🚩 <b>Открытые жалобы</b> — {len(rows_db)}", rows


@view("rep", "reports")
async def view_report(ctx: Ctx, report_id: str) -> ViewResult:
    r = await ctx.app.db.fetchone(
        "SELECT r.*, s.label FROM reports r LEFT JOIN shops s ON s.id = r.shop_id WHERE r.id = ?", (int(report_id),))
    if r is None:
        return await view_reports(ctx)
    tz = int(ctx.app.catalog.setting("tz_offset", 5))
    html = (f"🚩 <b>Жалоба #{r['id']}</b> ({'открыта' if r['status'] == 'open' else 'решена'})\n"
            f"Магазин: {escape(r['label'] or '—')}\n"
            f"От: <code>{r['user_id']}</code>\n"
            f"Когда: {fmt_date(r['created_at'], tz)}\n\n{escape(r['text'])}")
    rows: Rows = []
    if r["status"] == "open":
        rows.append([b("✅ Решено", f"x:repok:{r['id']}", "success")])
    rows.append([b("🏪 К магазину", f"a:shop:{r['shop_id']}"), b("👤 Автор", f"a:user:{r['user_id']}")])
    rows.append(back_btn("a:reps:0"))
    return html, rows


@action("repok", "reports")
async def act_report_ok(ctx: Ctx, report_id: str):
    await ctx.app.db.execute("UPDATE reports SET status = 'done' WHERE id = ?", (int(report_id),))
    await ctx.log("report.done", report_id)
    return "a:reps:0"
