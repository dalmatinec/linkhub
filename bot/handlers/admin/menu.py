"""Админка: дерево меню (кнопки главного экрана и подменю)."""
from html import escape

from aiogram.types import Message

from ...catalog import MenuItem
from ...richtext import normalize_url, parse_label
from ..user import screen_menu
from .core import (
    Ctx, InputError, Rows, ViewResult, action, b, back_btn, editor_rows, icon_line, media_line, on_input, snippet,
    style_name, view,
)
from ...ui import button

P = "menu"

KINDS = {
    "menu": "📂 Подменю (свои кнопки)",
    "tag": "🏷 Магазины с меткой",
    "all": "🗂 Все магазины",
    "cities": "🏙 Выбор города",
    "categories": "🗂 Категории (все города)",
    "search": "🔍 Поиск",
    "favorites": "⭐ Избранное",
    "apply": "📝 Заявка «Разместить магазин»",
    "language": "🌐 Выбор языка",
    "url": "🔗 Ссылка (канал, другой бот, сайт)",
}


def item_title(item: MenuItem) -> str:
    return ("" if item.is_active else "🙈 ") + (item.label or "—")


@view("item", P)
async def view_item(ctx: Ctx, item_id: str) -> ViewResult:
    app = ctx.app
    cat = app.catalog
    item = cat.menu.get(int(item_id))
    if item is None:
        item = cat.menu[cat.root_id]
    row = await app.db.fetchone("SELECT * FROM menu_items WHERE id = ?", (item.id,))
    is_root = item.id == cat.root_id
    sid = str(item.id)

    lines = [f"📋 <b>{'Главное меню (приветствие)' if is_root else escape(item.label)}</b>"]
    if is_root:
        lines.append("<i>Первый экран после /start. Можно вставить <code>{имя}</code> — имя пользователя.</i>")
    if not is_root:
        lines.append(f"Тип: {KINDS.get(item.kind, item.kind)}")
        lines.append(f"Иконка: {icon_line(item.icon)} · Цвет: {style_name(item.style)}")
        lines.append(f"Ряд: {item.row + 1} · Позиция в ряду: {item.position + 1}")
        lines.append(f"Статус: {'включена' if item.is_active else '🙈 скрыта'}")
        if item.kind == "tag":
            tag = cat.tags.get(int(item.payload or 0))
            lines.append(f"Метка: {escape(tag.label) if tag else '⚠️ не выбрана'}")
        if item.kind == "url":
            lines.append(f"Ссылка: {escape(item.payload or '⚠️ не задана')}")
    if item.kind != "url":
        lines.append(f"Медиа: {media_line(app, item.media_id)}")
        lines.append(f"\n<b>Текст экрана:</b>\n{snippet(item.html)}")
        if item.kind in ("cities", "search", "categories", "favorites", "apply", "language") and not item.html:
            lines.append("<i>(пусто — используется общий текст из раздела «Тексты»)</i>")
    if item.kind == "menu":
        lines.append("\n<b>Кнопки этого экрана</b> — нажмите, чтобы настроить:")

    rows: Rows = []
    if item.kind == "menu":
        by_row: dict[int, list] = {}
        for child in item.children:
            by_row.setdefault(child.row, []).append(b(item_title(child), f"a:item:{child.id}"))
        rows.extend(by_row[r] for r in sorted(by_row))
        rows.append([b("➕ Добавить кнопку", f"a:inew:{sid}", "success")])
    rows.extend(editor_rows("item", sid, row, label=not is_root, rich=item.kind != "url"))
    if item.kind == "tag":
        rows.append([b("🏷 Сменить метку", f"x:itag:{sid}")])
    if item.kind == "url":
        rows.append([b("🔗 Изменить ссылку", f"x:iurl:{sid}")])
    if not is_root:
        rows.append([b("⬆️ Ряд выше", f"x:irow:{sid}:-1"), b("⬇️ Ряд ниже", f"x:irow:{sid}:1")])
        rows.append([b("⬅️ Левее", f"x:ipos:{sid}:-1"), b("➡️ Правее", f"x:ipos:{sid}:1")])
        rows.append([b("↕️ В отдельный ряд", f"x:isolo:{sid}")])
        r = [b("🙈 Скрыть" if item.is_active else "👁 Показать", f"x:iact:{sid}")]
        if not item.is_system:
            r.append(b("🗑 Удалить", f"a:idel:{sid}", "danger"))
        rows.append(r)
    if item.kind == "menu":
        rows.append([b("👀 Предпросмотр", f"x:iprev:{sid}")])
    rows.append(back_btn(f"a:item:{item.parent_id}" if item.parent_id else "a:home"))
    return "\n".join(lines), rows


@view("inew", P)
async def view_item_new(ctx: Ctx, parent_id: str) -> ViewResult:
    rows = [[b(title, f"x:inew:{parent_id}:{kind}")] for kind, title in KINDS.items()]
    rows.append(back_btn(f"a:item:{parent_id}"))
    return "➕ <b>Новая кнопка</b>\nЧто она будет открывать?", rows


@action("inew", P)
async def act_item_new(ctx: Ctx, parent_id: str, kind: str):
    return await ctx.ask(
        "inew", "Отправьте текст кнопки. Премиум-эмодзи в начале станет иконкой.",
        f"a:inew:{parent_id}", parent_id, kind,
    )


@on_input("inew", P)
async def in_item_new(ctx: Ctx, message: Message, parent_id: str, kind: str):
    if not message.text:
        raise InputError("Нужен текст.")
    label, icon = parse_label(message)
    if not label:
        raise InputError("Пустой текст.")
    db = ctx.app.db
    next_row = await db.fetchval(
        "SELECT COALESCE(MAX(row), -1) + 1 FROM menu_items WHERE parent_id = ?", (int(parent_id),))
    payload = None
    if kind == "tag":
        payload = str(next(iter(ctx.app.catalog.tags), "")) or None
    item_id = await db.execute(
        "INSERT INTO menu_items(parent_id, kind, payload, label, icon, html, row, position) VALUES (?, ?, ?, ?, ?, ?, ?, 0)",
        (int(parent_id), kind, payload, label, icon, f"<b>{escape(label)}</b>" if kind in ("menu", "tag", "all") else "",
         next_row),
    )
    await ctx.reload()
    await ctx.log("menu.create", f"{item_id}: {label}")
    ctx.notice = "✅ Кнопка добавлена" + (" — теперь укажите ссылку «🔗 Изменить ссылку»." if kind == "url" else ".")
    return f"a:item:{item_id}"


@action("itag", P)
async def act_item_tag(ctx: Ctx, item_id: str):
    cat = ctx.app.catalog
    item = cat.menu.get(int(item_id))
    tag_ids = list(cat.tags)
    if not item or not tag_ids:
        return f"a:item:{item_id}"
    cur = int(item.payload or 0)
    nxt = tag_ids[(tag_ids.index(cur) + 1) % len(tag_ids)] if cur in tag_ids else tag_ids[0]
    await ctx.app.db.execute("UPDATE menu_items SET payload = ? WHERE id = ?", (str(nxt), item.id))
    await ctx.reload()
    return f"a:item:{item_id}"


@action("iurl", P)
async def act_item_url(ctx: Ctx, item_id: str):
    return await ctx.ask("iurl", "Отправьте ссылку: https://…, t.me/… или @username", f"a:item:{item_id}", item_id)


@on_input("iurl", P)
async def in_item_url(ctx: Ctx, message: Message, item_id: str):
    url = normalize_url(message.text or "")
    if url is None:
        raise InputError("Это не похоже на ссылку.")
    await ctx.app.db.execute("UPDATE menu_items SET payload = ? WHERE id = ?", (url, int(item_id)))
    await ctx.reload()
    return f"a:item:{item_id}"


@action("irow", P)
async def act_item_row(ctx: Ctx, item_id: str, delta: str):
    db = ctx.app.db
    item = ctx.app.catalog.menu.get(int(item_id))
    if item is None:
        return "a:home"
    new_row = max(0, item.row + int(delta))
    # в конец нового ряда
    pos = await db.fetchval(
        "SELECT COALESCE(MAX(position), -1) + 1 FROM menu_items WHERE parent_id = ? AND row = ? AND id != ?",
        (item.parent_id, new_row, item.id))
    await db.execute("UPDATE menu_items SET row = ?, position = ? WHERE id = ?", (new_row, pos, item.id))
    await _compact_rows(ctx, item.parent_id)
    return f"a:item:{item_id}"


@action("isolo", P)
async def act_item_solo(ctx: Ctx, item_id: str):
    """Выносит кнопку в собственный ряд сразу под текущим."""
    db = ctx.app.db
    item = ctx.app.catalog.menu.get(int(item_id))
    if item is None:
        return "a:home"
    await db.execute("UPDATE menu_items SET row = row + 1 WHERE parent_id = ? AND row > ?", (item.parent_id, item.row))
    await db.execute("UPDATE menu_items SET row = ?, position = 0 WHERE id = ?", (item.row + 1, item.id))
    await _compact_rows(ctx, item.parent_id)
    return f"a:item:{item_id}"


async def _compact_rows(ctx: Ctx, parent_id: int | None) -> None:
    """Убирает «дыры» в номерах рядов и позиций."""
    db = ctx.app.db
    rows = await db.fetchall("SELECT id, row FROM menu_items WHERE parent_id = ? ORDER BY row, position, id", (parent_id,))
    mapping: dict[int, int] = {}
    updates = []
    counters: dict[int, int] = {}
    for r in rows:
        new_row = mapping.setdefault(r["row"], len(mapping))
        pos = counters.get(new_row, 0)
        counters[new_row] = pos + 1
        updates.append((new_row, pos, r["id"]))
    await db.executemany("UPDATE menu_items SET row = ?, position = ? WHERE id = ?", updates)
    await ctx.reload()


@action("ipos", P)
async def act_item_pos(ctx: Ctx, item_id: str, delta: str):
    db = ctx.app.db
    item = ctx.app.catalog.menu.get(int(item_id))
    if item is None:
        return "a:home"
    ids = [r["id"] for r in await db.fetchall(
        "SELECT id FROM menu_items WHERE parent_id = ? AND row = ? ORDER BY position, id", (item.parent_id, item.row))]
    i = ids.index(item.id)
    j = min(max(i + int(delta), 0), len(ids) - 1)
    ids.insert(j, ids.pop(i))
    await db.executemany("UPDATE menu_items SET position = ? WHERE id = ?", ((p, x) for p, x in enumerate(ids)))
    await ctx.reload()
    return f"a:item:{item_id}"


@action("iact", P)
async def act_item_active(ctx: Ctx, item_id: str):
    await ctx.app.db.execute("UPDATE menu_items SET is_active = 1 - is_active WHERE id = ?", (int(item_id),))
    await ctx.reload()
    await ctx.log("menu.toggle", item_id)
    return f"a:item:{item_id}"


@view("idel", P)
async def view_item_delete(ctx: Ctx, item_id: str) -> ViewResult:
    item = ctx.app.catalog.menu.get(int(item_id))
    extra = " и все кнопки внутри неё" if item and item.children else ""
    return (f"🗑 Удалить кнопку <b>{escape(item.label if item else item_id)}</b>{extra}?",
            [[b("🗑 Да, удалить", f"x:idel:{item_id}", "danger"), b("✖️ Отмена", f"a:item:{item_id}")]])


@action("idel", P)
async def act_item_delete(ctx: Ctx, item_id: str):
    item = ctx.app.catalog.menu.get(int(item_id))
    if item is None or item.is_system:
        return "a:home"
    await ctx.app.db.execute("DELETE FROM menu_items WHERE id = ?", (item.id,))
    await _compact_rows(ctx, item.parent_id)
    await ctx.log("menu.delete", f"{item.id}: {item.label}")
    ctx.notice = "🗑 Кнопка удалена."
    return f"a:item:{item.parent_id}"


@action("iprev", P)
async def act_item_preview(ctx: Ctx, item_id: str):
    app = ctx.app
    item = app.catalog.menu.get(int(item_id))
    if item is None:
        return "a:home"
    html, media_id, kb = screen_menu(app, app.catalog.tr(app.catalog.base_lang), item, "Имя")
    # в предпросмотре кнопки неактивны — чтобы не уводить в каталог
    for r in kb.inline_keyboard:
        for i, btn in enumerate(r):
            if btn.callback_data:
                r[i] = btn.model_copy(update={"callback_data": "noop"})
    kb.inline_keyboard.append([button("✖️ Закрыть предпросмотр", cb="x:close")])
    msg = await app.media.send(app.bot, ctx.chat_id, media_id, html, kb) if media_id else None
    if msg is None:
        await app.bot.send_message(ctx.chat_id, html, reply_markup=kb)
    await ctx.toast("Предпросмотр отправлен ниже")
    return None
