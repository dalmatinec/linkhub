"""Админка: дерево меню (кнопки главного экрана и подменю)."""
from html import escape

from aiogram.types import Message

from ...catalog import MenuItem
from ...richtext import normalize_url, parse_label
from ..user import screen_menu
from .core import (
    Ctx, InputError, Rows, ViewResult, action, b, back_btn, editor_extras, editor_rows, media_line, on_input, snippet,
    view,
)
from ...ui import button

P = "menu"

KINDS = {
    "menu": "📂 Подменю (свои кнопки)",
    "tag": "🏷 Магазины с меткой",
    "all": "🗂 Все магазины",
    "city_block": "🏙 Блок городов (главные города + Другие города)",
    "cities": "🏙 Выбор города (отдельным экраном)",
    "search": "🔍 Поиск",
    "favorites": "⭐ Избранное",
    "apply": "📝 Заявка на размещение магазина",
    "language": "🌐 Выбор языка",
    "url": "🔗 Ссылка (канал, другой бот, сайт)",
}


def item_title(item: MenuItem) -> str:
    label = "🏙 Кнопки городов" if item.kind == "city_block" else (item.label or "без названия")
    return ("" if item.is_active else "🙈 ") + label


NO_SCREEN = ("url", "city_block")  # у этих кнопок нет своего экрана с текстом


def layout_rows(ctx: Ctx, parent: MenuItem, make_cb, mark_id: int = 0) -> Rows:
    """Кнопки меню так, как их видит пользователь. Блок городов показан настоящими кнопками городов.
    make_cb(child, city_id) -> callback; city_id=0 у обычной кнопки, -1 у «Другие города»."""
    cat = ctx.app.catalog
    buttons: dict[int, list] = {}
    blocks: dict[int, Rows] = {}
    per_row = int(cat.setting("per_row", 2))
    for child in parent.children:
        mark = "👉 " if child.id == mark_id else ""
        if child.kind == "city_block":
            cities = [b(mark + ("" if c.is_active else "🙈 ") + c.label, make_cb(child, c.id)) for c in cat.main_cities]
            if cat.other_cities:
                cities.append(b(mark + cat.button("other_cities").label, make_cb(child, -1)))
            blocks.setdefault(child.row, []).extend(cities[i:i + per_row] for i in range(0, len(cities), per_row))
        else:
            buttons.setdefault(child.row, []).append(b(mark + item_title(child), make_cb(child, 0)))
    rows: Rows = []
    for key in sorted(set(buttons) | set(blocks)):
        if key in buttons:
            rows.append(buttons[key])
        rows.extend(blocks.get(key, []))
    return rows


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
    rows: Rows = []

    if is_root:
        lines = ["📋 <b>Главное меню</b>",
                 "Первый экран после /start. В тексте можно написать <code>{имя}</code>, бот подставит имя человека.",
                 f"Картинка: {media_line(app, item.media_id)}",
                 f"\n<b>Текст:</b>\n{snippet(item.html)}",
                 "\n<b>Кнопки</b> (нажмите, чтобы настроить):"]
    else:
        lines = [f"🔘 <b>{escape(item_title(item))}</b>",
                 f"Что открывает: {KINDS.get(item.kind, item.kind)}"]
        if not item.is_active:
            lines.append("🙈 Скрыта, пользователи её не видят")
        if item.kind == "tag":
            tag = cat.tags.get(int(item.payload or 0))
            lines.append(f"Метка: {escape(tag.label) if tag else '⚠️ не выбрана'}")
        if item.kind == "url":
            lines.append(f"Ссылка: {escape(item.payload or '⚠️ не задана')}")
        if item.kind == "city_block":
            lines.append("Это кнопки городов: главные города ⭐ по 2 в ряд и 🌍 Другие города. "
                         "Какие города главные, настраивается в разделе 🏙 Города.")
        if item.kind not in NO_SCREEN:
            lines.append(f"Картинка: {media_line(app, item.media_id)}")
            lines.append(f"\n<b>Текст экрана:</b>\n{snippet(item.html)}")
            if item.kind in ("cities", "search", "categories", "favorites", "apply", "language") and not item.html:
                lines.append("<i>Пусто, поэтому используется общий текст из раздела 📝 Тексты.</i>")
        if item.kind != "city_block":
            lines.append("\nТак кнопка выглядит у пользователей 👇")
            rows.append([button(item.label, item.icon, item.style, cb="noop")])
        if item.kind == "menu":
            lines.append("\n<b>Кнопки внутри</b> (нажмите, чтобы настроить):")

    if item.kind == "menu":
        def open_cb(child: MenuItem, city_id: int) -> str:
            if child.kind == "city_block":  # город — настраивается как обычная кнопка
                return f"a:city:{city_id}" if city_id > 0 else "a:btn:other_cities"
            return f"a:item:{child.id}"
        rows.extend(layout_rows(ctx, item, open_cb))
        rows.append([b("➕ Добавить кнопку", f"a:inew:{sid}", "success"),
                     b("↕️ Расстановка", f"a:arr:{sid}:0")])

    rows.extend(editor_rows("item", sid, row, label=not is_root and item.kind != "city_block",
                            rich=item.kind not in NO_SCREEN, app=app, compact=True))
    if not is_root:
        rows.append([b("↕️ Переставить", f"a:arr:{item.parent_id}:{sid}"), b("⚙️ Ещё", f"a:imore:{sid}")])
    else:
        rows.append([b("👀 Предпросмотр", f"x:iprev:{sid}"), b("⚙️ Ещё", f"a:imore:{sid}")])
    rows.append(back_btn(f"a:item:{item.parent_id}" if item.parent_id else "a:cfg"))
    return "\n".join(lines), rows


@view("imore", P)
async def view_item_more(ctx: Ctx, item_id: str) -> ViewResult:
    app = ctx.app
    item = app.catalog.menu.get(int(item_id))
    if item is None:
        return await view_item(ctx, str(app.catalog.root_id))
    row = await app.db.fetchone("SELECT * FROM menu_items WHERE id = ?", (item.id,))
    sid = str(item.id)
    is_root = item.id == app.catalog.root_id
    rows: Rows = editor_extras("item", sid, row, app=app, label=not is_root, rich=item.kind not in NO_SCREEN)
    if item.kind == "tag":
        rows.append([b("🏷 Сменить метку", f"x:itag:{sid}")])
    if item.kind == "url":
        rows.append([b("🔗 Изменить ссылку", f"x:iurl:{sid}")])
    if item.kind == "menu" and not is_root:
        rows.append([b("👀 Предпросмотр", f"x:iprev:{sid}")])
    if not is_root:
        r = [b("🙈 Скрыть" if item.is_active else "👁 Показать", f"x:iact:{sid}")]
        if not item.is_system:
            r.append(b("🗑 Удалить", f"a:idel:{sid}", "danger"))
        rows.append(r)
    rows.append(back_btn(f"a:item:{sid}"))
    return f"⚙️ <b>{escape(item_title(item))}</b>: дополнительно", rows


# ---------- расстановка ----------
@view("arr", P)
async def view_arrange(ctx: Ctx, parent_id: str, selected: str = "0") -> ViewResult:
    cat = ctx.app.catalog
    parent = cat.menu.get(int(parent_id)) or cat.menu[cat.root_id]
    sel = int(selected)
    rows: Rows = layout_rows(ctx, parent, lambda child, _city: f"a:arr:{parent.id}:{child.id}", sel)
    if sel and sel in cat.menu:
        p, s = parent.id, sel
        rows.append([b("⬅️", f"x:arrmv:{p}:{s}:L"), b("⬆️", f"x:arrmv:{p}:{s}:U"),
                     b("⬇️", f"x:arrmv:{p}:{s}:D"), b("➡️", f"x:arrmv:{p}:{s}:R")])
        chosen = cat.menu[s]
        rows.append([b("✏️ Настроить выбранную",
                       "a:cities:0" if chosen.kind == "city_block" else f"a:item:{s}")])
    rows.append([b("✅ Готово", f"a:item:{parent.id}", "success")])
    html = ("↕️ <b>Расстановка кнопок</b>\n\n"
            "Нажмите кнопку, чтобы выбрать её (👉), и двигайте стрелками.\n"
            "⬅️ ➡️ меняют порядок в ряду.\n"
            "⬆️ ⬇️ двигают по шагу: если в ряду несколько кнопок, выбранная уходит в отдельный ряд, "
            "следующее нажатие ставит её к соседнему ряду.")
    return html, rows


@action("arrmv", P)
async def act_arrange_move(ctx: Ctx, parent_id: str, item_id: str, direction: str):
    item = ctx.app.catalog.menu.get(int(item_id))
    if item is not None:
        if direction in ("U", "D"):
            await _move_row(ctx, item, 1 if direction == "D" else -1)
        else:
            await _move_pos(ctx, item, 1 if direction == "R" else -1)
    return f"a:arr:{parent_id}:{item_id}"


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
    ctx.notice = "✅ Кнопка добавлена." + (" Теперь укажите ссылку: ⚙️ Ещё → 🔗 Изменить ссылку." if kind == "url" else "")
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
    item = ctx.app.catalog.menu.get(int(item_id))
    if item is None:
        return "a:home"
    await _move_row(ctx, item, int(delta))
    return f"a:item:{item_id}"


async def _move_row(ctx: Ctx, item: MenuItem, delta: int) -> None:
    """Стрелки рядов по шагу:
    кнопка в ряду не одна — отрывается в новый ряд сразу под/над текущим;
    кнопка уже одна — приклеивается к соседнему ряду."""
    db = ctx.app.db
    down = delta > 0
    parent, row = item.parent_id, item.row
    if item.kind == "city_block":
        target = row + (1 if down else -1)
        if target < 0 or not await db.fetchval("SELECT 1 FROM menu_items WHERE parent_id = ? AND row = ?",
                                                (parent, target)):
            ctx.notice = "Блок уже в самом низу." if down else "Блок уже в самом верху."
            return
        await db.execute("UPDATE menu_items SET row = ? WHERE parent_id = ? AND row = ?", (row, parent, target))
        await db.execute("UPDATE menu_items SET row = ? WHERE id = ?", (target, item.id))
        await _compact_rows(ctx, parent)
        return
    shares_row = await db.fetchval(
        "SELECT COUNT(*) FROM menu_items WHERE parent_id = ? AND row = ? AND id != ?", (parent, row, item.id))
    if shares_row:
        edge = row + 1 if down else row  # освобождаем место: ряды ниже сдвигаем на один
        await db.execute("UPDATE menu_items SET row = row + 1 WHERE parent_id = ? AND row >= ? AND id != ?",
                         (parent, edge, item.id))
        await db.execute("UPDATE menu_items SET row = ?, position = 0 WHERE id = ?", (edge, item.id))
    else:
        target = row + (1 if down else -1)
        exists = await db.fetchval("SELECT 1 FROM menu_items WHERE parent_id = ? AND row = ?", (parent, target))
        if not exists:
            ctx.notice = "Кнопка уже в самом низу." if down else "Кнопка уже в самом верху."
            return
        if await db.fetchval("SELECT 1 FROM menu_items WHERE parent_id = ? AND row = ? AND kind = 'city_block'",
                             (parent, target)):
            # блок городов всегда в своих рядах: кнопка перепрыгивает его целиком
            await db.execute("UPDATE menu_items SET row = ? WHERE parent_id = ? AND row = ?", (row, parent, target))
            await db.execute("UPDATE menu_items SET row = ? WHERE id = ?", (target, item.id))
            await _compact_rows(ctx, parent)
            return
        # сверху пришла — встаёт первой, снизу — последней
        pos = -1 if down else await db.fetchval(
            "SELECT COALESCE(MAX(position), -1) + 1 FROM menu_items WHERE parent_id = ? AND row = ?", (parent, target))
        await db.execute("UPDATE menu_items SET row = ?, position = ? WHERE id = ?", (target, pos, item.id))
    await _compact_rows(ctx, parent)


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
    item = ctx.app.catalog.menu.get(int(item_id))
    if item is None:
        return "a:home"
    await _move_pos(ctx, item, int(delta))
    return f"a:item:{item_id}"


async def _move_pos(ctx: Ctx, item: MenuItem, delta: int) -> None:
    db = ctx.app.db
    ids = [r["id"] for r in await db.fetchall(
        "SELECT id FROM menu_items WHERE parent_id = ? AND row = ? ORDER BY position, id", (item.parent_id, item.row))]
    i = ids.index(item.id)
    j = min(max(i + delta, 0), len(ids) - 1)
    ids.insert(j, ids.pop(i))
    await db.executemany("UPDATE menu_items SET position = ? WHERE id = ?", ((p, x) for p, x in enumerate(ids)))
    await ctx.reload()


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
    html, media_id, kb = screen_menu(app, app.catalog.tr(app.catalog.base_lang), item, "Имя", ctx.user_id)
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
