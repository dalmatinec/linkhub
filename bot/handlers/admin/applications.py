"""Админка: заявки «Разместить магазин» и редактор анкеты."""
import json
import re
from html import escape

from aiogram.exceptions import TelegramAPIError
from aiogram.types import Message

from ...catalog import now
from ...richtext import LABEL_LIMIT, normalize_url, parse_label
from ...ui import button, fill, markup, paginate
from .core import Ctx, InputError, Rows, ViewResult, action, b, back_btn, move, on_input, snippet, view
from .shops import fmt_date

P = "applications"
STATUS = {"new": "🆕 новая", "accepted": "✅ одобрена", "rejected": "❌ отклонена"}
KIND_NAMES = {"text": "текст", "media": "фото/GIF/видео", "any": "текст или фото"}
ROLE_NAMES = {
    "": "никуда (только для модератора)", "name": "название магазина", "description": "текст карточки",
    "price": "прайс (в конец карточки)", "contacts": "кнопки-контакты", "cities": "города", "media": "фото карточки",
}


# ---------- заявки ----------
@view("appls", P)
async def view_applications(ctx: Ctx, status: str = "new", page: str = "0") -> ViewResult:
    db = ctx.app.db
    rows_db = await db.fetchall(
        "SELECT id, user_id, answers, created_at FROM applications WHERE status = ? ORDER BY created_at DESC",
        (status,))
    chunk, p, pages = paginate(rows_db, int(page), 15)
    rows: Rows = []
    for r in chunk:
        answers = json.loads(r["answers"])
        name = next((a["plain"] for a in answers if a["role"] == "name" and a["plain"]), f"#{r['id']}")
        rows.append([b(f"#{r['id']} · {name[:40]}", f"a:appl:{r['id']}")])
    nav = []
    if p > 0:
        nav.append(b("◀️", f"a:appls:{status}:{p - 1}"))
    if pages > 1:
        nav.append(button(f"{p + 1}/{pages}", cb="noop"))
    if p < pages - 1:
        nav.append(b("▶️", f"a:appls:{status}:{p + 1}"))
    rows.append(nav)
    rows.append([b(("• " if s == status else "") + t, f"a:appls:{s}:0") for s, t in STATUS.items()])
    rows.append([b("⚙️ Вопросы анкеты", "a:flds")])
    rows.append(back_btn("a:home"))
    html = (f"📝 <b>Заявки</b>, {STATUS[status]}: {len(rows_db)}\n\n"
            "Люди заполняют анкету через кнопку меню 📝 Разместить магазин. Из заявки одной кнопкой "
            "создаётся черновик карточки, останется проверить его и опубликовать.")
    return html, rows


@view("appl", P)
async def view_application(ctx: Ctx, app_id: str) -> ViewResult:
    app = ctx.app
    r = await app.db.fetchone("SELECT * FROM applications WHERE id = ?", (int(app_id),))
    if r is None:
        return await view_applications(ctx)
    user = await app.db.fetchone("SELECT username, first_name FROM users WHERE id = ?", (r["user_id"],))
    who = ""
    if user:
        who = f"@{escape(user['username'])}" if user["username"] else escape(user["first_name"] or "")
    tz = int(app.catalog.setting("tz_offset", 5))
    answers = json.loads(r["answers"])
    parts = [
        f"📝 <b>Заявка #{r['id']}</b>, {STATUS.get(r['status'], r['status'])}",
        f"От: {who} <a href=\"tg://user?id={r['user_id']}\">написать</a> (<code>{r['user_id']}</code>)",
        f"Когда: {fmt_date(r['created_at'], tz)}",
    ]
    if r["note"]:
        parts.append(f"Комментарий: {escape(r['note'])}")
    for a in answers:
        value = a["html"] or ""
        if len(a["plain"]) > 600:  # длинные ответы — обрезанным текстом, чтобы влезть в сообщение
            value = escape(a["plain"][:600]) + "…"
        if a["media_id"]:
            value = ("📎 медиа\n" + value).strip()
        parts.append(f"\n<b>{escape(a['label'])}</b>\n{value or '<i>пропущено</i>'}")
    rows: Rows = []
    if any(a["media_id"] for a in answers):
        rows.append([b("👀 Показать медиа", f"x:aplmed:{r['id']}")])
    if r["status"] == "new":
        rows.append([b("✅ Создать магазин (черновик)", f"x:aplok:{r['id']}", "success")])
        rows.append([b("❌ Отклонить", f"x:aplno:{r['id']}", "danger"), b("💬 Ответить", f"x:aplmsg:{r['id']}")])
    else:
        rows.append([b("💬 Написать автору", f"x:aplmsg:{r['id']}")])
    if r["shop_id"]:
        rows.append([b("🏪 Открыть магазин", f"a:shop:{r['shop_id']}")])
    rows.append([b("👤 Автор", f"a:user:{r['user_id']}")])
    rows.append(back_btn(f"a:appls:{r['status']}:0"))
    return "\n".join(parts), rows


@action("aplmed", P)
async def act_application_media(ctx: Ctx, app_id: str):
    r = await ctx.app.db.fetchone("SELECT answers FROM applications WHERE id = ?", (int(app_id),))
    close = [[button("✖️ Закрыть", cb="x:close")]]
    for a in json.loads(r["answers"]) if r else []:
        if a["media_id"]:
            await ctx.app.media.send(ctx.app.bot, ctx.chat_id, a["media_id"], f"📎 {escape(a['label'])}", markup(close))
    await ctx.toast("Медиа отправлены ниже")
    return None


def _contacts_from_text(text: str) -> list[tuple[str, str]]:
    """Строки заявки → кнопки-контакты. «Текст | ссылка», @username или ссылка."""
    out: list[tuple[str, str]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if "|" in line:
            label, raw = line.rsplit("|", 1)
            url = normalize_url(raw)
            if url:
                out.append((" ".join(label.split())[:LABEL_LIMIT] or "Связаться", url))
            continue
        for token in re.findall(r"@[A-Za-z0-9_]{4,32}|(?:https?://|t\.me/)\S+", line):
            url = normalize_url(token)
            if url:
                out.append((f"💬 {token}" if token.startswith("@") else "🔗 Ссылка", url))
    return out[:8]


@action("aplok", P)
async def act_application_accept(ctx: Ctx, app_id: str):
    app = ctx.app
    db, cat = app.db, app.catalog
    r = await db.fetchone("SELECT * FROM applications WHERE id = ? AND status = 'new'", (int(app_id),))
    if r is None:
        return f"a:appl:{app_id}"
    answers = json.loads(r["answers"])
    by_role: dict[str, list[dict]] = {}
    for a in answers:
        by_role.setdefault(a["role"], []).append(a)

    name = next((a["plain"] for a in by_role.get("name", []) if a["plain"]), f"Магазин #{app_id}")
    label = " ".join(name.split())[:LABEL_LIMIT]
    html_parts = [f"<b>{escape(label)}</b>"]
    html_parts += [a["html"] for a in by_role.get("description", []) if a["html"]]
    html_parts += [a["html"] for a in by_role.get("price", []) if a["html"]]
    html = "\n\n".join(html_parts)
    plain = "\n".join(a["plain"] for role in ("description", "price") for a in by_role.get(role, []))
    media_id = next((a["media_id"] for a in by_role.get("media", []) if a["media_id"]), None) \
        or next((a["media_id"] for a in answers if a["media_id"]), None)
    note = ""
    if len(plain) > 1024 and media_id:
        note = "\n⚠️ Текст длиннее 1024 символов, поэтому картинка не прикреплена. Сократите текст и добавьте фото."
        media_id = None

    ts = now()
    pos = (await db.fetchval("SELECT COALESCE(MAX(position), -1) + 1 FROM shops")) or 0
    shop_id = await db.execute(
        "INSERT INTO shops(label, html, plain, media_id, position, is_active, created_at, updated_at)"
        " VALUES (?, ?, ?, ?, ?, 0, ?, ?)", (label, html, plain, media_id, pos, ts, ts))
    contacts = [c for a in by_role.get("contacts", []) for c in _contacts_from_text(a["plain"])]
    await db.executemany("INSERT INTO shop_contacts(shop_id, label, url, position) VALUES (?, ?, ?, ?)",
                         ((shop_id, lbl, url, i) for i, (lbl, url) in enumerate(contacts)))
    city_text = " ".join(a["plain"] for a in by_role.get("cities", [])).casefold()
    if city_text:
        if "все" in city_text.split() or city_text.strip() in ("все", "все города", "all"):
            city_ids = list(cat.cities)
        else:
            city_ids = [c.id for c in cat.cities.values() if c.label.casefold() in city_text]
        await db.executemany("INSERT OR IGNORE INTO shop_cities(shop_id, city_id) VALUES (?, ?)",
                             ((shop_id, c) for c in city_ids))
    await db.execute(
        "UPDATE applications SET status = 'accepted', shop_id = ?, reviewed_by = ?, reviewed_at = ? WHERE id = ?",
        (shop_id, ctx.user_id, ts, int(app_id)))
    await ctx.reload()
    await ctx.log("appl.accept", f"#{app_id} → {label}")
    await _notify_author(ctx, r["user_id"], "apply_accepted")
    ctx.notice = ("✅ Создан черновик магазина (скрыт). Проверьте карточку, метки, категории и опубликуйте."
                  + note)
    return f"a:shop:{shop_id}"


async def _notify_author(ctx: Ctx, user_id: int, text_key: str, **values) -> bool:
    app = ctx.app
    tr = app.catalog.tr(app.user_lang(user_id, None))
    try:
        await app.bot.send_message(user_id, fill(tr.text(text_key), **values))
        return True
    except TelegramAPIError:
        return False


@action("aplno", P)
async def act_application_reject(ctx: Ctx, app_id: str):
    return await ctx.ask("aplno", "Напишите причину отказа, её получит автор заявки.\n"
                                  "Чтобы отклонить без причины, отправьте знак минус: -", f"a:appl:{app_id}", app_id)


@on_input("aplno", P)
async def in_application_reject(ctx: Ctx, message: Message, app_id: str):
    reason = (message.text or "").strip()
    if not reason:
        raise InputError("Нужен текст или знак минус.")
    reason = "" if reason == "-" else reason[:1000]
    r = await ctx.app.db.fetchone("SELECT user_id FROM applications WHERE id = ?", (int(app_id),))
    await ctx.app.db.execute(
        "UPDATE applications SET status = 'rejected', note = ?, reviewed_by = ?, reviewed_at = ? WHERE id = ?",
        (reason or None, ctx.user_id, now(), int(app_id)))
    await ctx.log("appl.reject", f"#{app_id}")
    if r:
        await _notify_author(ctx, r["user_id"], "apply_rejected", reason=reason)
    ctx.notice = "❌ Заявка отклонена, автор уведомлён."
    return f"a:appl:{app_id}"


@action("aplmsg", P)
async def act_application_message(ctx: Ctx, app_id: str):
    return await ctx.ask("aplmsg", "Напишите сообщение автору заявки. Бот отправит его от своего имени.",
                         f"a:appl:{app_id}", app_id)


@on_input("aplmsg", P)
async def in_application_message(ctx: Ctx, message: Message, app_id: str):
    if not message.text:
        raise InputError("Нужен текст.")
    r = await ctx.app.db.fetchone("SELECT user_id FROM applications WHERE id = ?", (int(app_id),))
    if r is None:
        return "a:appls:new:0"
    ok = await _notify_author(ctx, r["user_id"], "moderator_message", text=message.text[:3000])
    await ctx.log("appl.reply", f"#{app_id}")
    ctx.notice = "✅ Сообщение отправлено." if ok else "⚠️ Не доставлено: пользователь заблокировал бота."
    return f"a:appl:{app_id}"


# ---------- анкета ----------
@view("flds", P)
async def view_fields(ctx: Ctx) -> ViewResult:
    cat = ctx.app.catalog
    rows: Rows = [[b(f"{i}. {f.label}{'' if f.required else ' (необяз.)'}", f"a:fld:{f.id}")]
                  for i, f in enumerate(cat.fields, 1)]
    rows.append([b("➕ Добавить вопрос", "x:fldnew", "success")])
    rows.append(back_btn("a:appls:new:0"))
    html = ("⚙️ <b>Вопросы анкеты для размещения магазина</b>\n\n"
            "Бот задаёт их по порядку. У каждого вопроса есть роль: куда попадёт ответ, "
            "когда вы создадите магазин из заявки (название, текст карточки, контакты…).")
    return html, rows


@action("fldnew", P)
async def act_field_new(ctx: Ctx):
    return await ctx.ask("fldnew", "Отправьте короткое название вопроса, например: Скрин оплаты. "
                                   "Сам текст вопроса настроите следующим шагом.", "a:flds")


@on_input("fldnew", P)
async def in_field_new(ctx: Ctx, message: Message):
    label, _ = parse_label(message)
    if not label:
        raise InputError("Нужен текст.")
    db = ctx.app.db
    pos = (await db.fetchval("SELECT COALESCE(MAX(position), -1) + 1 FROM app_fields")) or 0
    field_id = await db.execute(
        "INSERT INTO app_fields(label, html, kind, role, required, position) VALUES (?, ?, 'text', '', 1, ?)",
        (label, escape(label), pos))
    await ctx.reload()
    await ctx.log("field.create", label)
    ctx.notice = "✅ Вопрос добавлен. Нажмите 📝 Текст вопроса и напишите, что спросить."
    return f"a:fld:{field_id}"


@view("fld", P)
async def view_field(ctx: Ctx, field_id: str) -> ViewResult:
    f = next((x for x in ctx.app.catalog.fields if x.id == int(field_id)), None)
    if f is None:
        return await view_fields(ctx)
    html = (f"❓ <b>{escape(f.label)}</b>\n"
            f"Ответ: {KIND_NAMES.get(f.kind, f.kind)}\n"
            f"Обязательный: {'да' if f.required else 'нет (можно пропустить)'}\n"
            f"Куда попадёт в карточке: {ROLE_NAMES.get(f.role, f.role)}\n\n"
            f"<b>Вопрос:</b>\n{snippet(f.html, 600)}")
    fid = str(f.id)
    rows: Rows = [
        [b("✏️ Название", f"x:lbl:field:{fid}"), b("📝 Текст вопроса", f"x:htm:field:{fid}")],
        [b(f"Ответ: {KIND_NAMES.get(f.kind, f.kind)}", f"x:fldk:{fid}")],
        [b("Обязательный: да" if f.required else "Обязательный: нет", f"x:fldr:{fid}")],
        [b(f"Роль: {ROLE_NAMES.get(f.role, f.role)}", f"x:fldrole:{fid}")],
        [b("⬆️ Выше", f"x:fldmv:{fid}:-1"), b("⬇️ Ниже", f"x:fldmv:{fid}:1")],
        [b("🌐 Перевод на другие языки", f"a:trl:field:{fid}")],
        [b("🗑 Удалить", f"x:flddel:{fid}", "danger")],
        back_btn("a:flds"),
    ]
    return html, rows


async def _cycle(ctx: Ctx, field_id: str, column: str, values: list[str]):
    f = next((x for x in ctx.app.catalog.fields if x.id == int(field_id)), None)
    if f is not None:
        cur = getattr(f, column)
        nxt = values[(values.index(cur) + 1) % len(values)] if cur in values else values[0]
        await ctx.app.db.execute(f"UPDATE app_fields SET {column} = ? WHERE id = ?", (nxt, f.id))
        await ctx.reload()
    return f"a:fld:{field_id}"


@action("fldk", P)
async def act_field_kind(ctx: Ctx, field_id: str):
    return await _cycle(ctx, field_id, "kind", list(KIND_NAMES))


@action("fldrole", P)
async def act_field_role(ctx: Ctx, field_id: str):
    return await _cycle(ctx, field_id, "role", list(ROLE_NAMES))


@action("fldr", P)
async def act_field_required(ctx: Ctx, field_id: str):
    await ctx.app.db.execute("UPDATE app_fields SET required = 1 - required WHERE id = ?", (int(field_id),))
    await ctx.reload()
    return f"a:fld:{field_id}"


@action("fldmv", P)
async def act_field_move(ctx: Ctx, field_id: str, delta: str):
    await move(ctx, "app_fields", int(field_id), int(delta))
    return f"a:fld:{field_id}"


@action("flddel", P)
async def act_field_delete(ctx: Ctx, field_id: str):
    await ctx.app.db.execute("DELETE FROM app_fields WHERE id = ?", (int(field_id),))
    await ctx.reload()
    await ctx.log("field.delete", field_id)
    return "a:flds"
