"""Админка: тексты, системные кнопки, города, метки."""
from html import escape

from aiogram.types import Message

from ...richtext import parse_label
from ...ui import button, grid, paginate
from .core import (
    Ctx, InputError, Rows, ViewResult, action, b, back_btn, editor_rows, icon_line, media_line, move, on_input,
    style_name, view,
)

TEXT_NAMES = {
    "cities": "🏙 Экран выбора города",
    "other_cities": "🌍 Экран Другие города",
    "city_shops": "🏙 Список магазинов города",
    "empty": "📭 Когда в списке пусто",
    "search_prompt": "🔍 Приглашение к поиску",
    "search_results": "🔍 Результаты поиска",
    "search_empty": "🔍 Ничего не найдено",
    "report_prompt": "🚩 Просьба описать жалобу",
    "report_thanks": "🚩 Спасибо за жалобу",
    "report_limit": "🚩 Слишком частые жалобы",
    "verified_badge": "✅ Плашка Проверенный магазин",
    "banned": "🚫 Сообщение забаненному",
    "flood": "🐢 Слишком быстро (антифлуд)",
    "shop_unavailable": "🙈 Магазин недоступен",
    "city_categories": "🗂 Категории внутри города",
    "city_category_shops": "🗂 Магазины города в категории",
    "categories": "🗂 Экран Категории",
    "category_shops": "🗂 Магазины категории",
    "favorites": "⭐ Заголовок Избранное",
    "favorites_empty": "⭐ Пустое избранное",
    "fav_added": "⭐ Добавлено в избранное",
    "fav_removed": "⭐ Убрано из избранного",
    "language": "🌐 Экран выбора языка",
    "apply_intro": "📝 Заявка: вступление",
    "apply_step": "📝 Заявка: Шаг N из M",
    "apply_wrong": "📝 Заявка: неверный ответ",
    "apply_confirm": "📝 Заявка: проверка перед отправкой",
    "apply_done": "📝 Заявка: отправлена",
    "apply_pending": "📝 Заявка: уже на рассмотрении",
    "apply_cooldown": "📝 Заявка: слишком часто",
    "apply_accepted": "📝 Заявка одобрена (сообщение автору)",
    "apply_rejected": "📝 Заявка отклонена (сообщение автору)",
    "moderator_message": "💬 Сообщение модератора автору заявки",
    "card_cities": "🏙 Строка городов в карточке",
    "card_cities_all": "🏙 Карточка: работает во всех городах",
    "contact_greeting": "👋 Приветствие оператору от покупателя",
}
# Где показывается текст и что в него можно подставить
TEXT_HELP = {
    "cities": ("Над кнопками городов на отдельном экране выбора города.", {}),
    "other_cities": ("Вверху экрана после нажатия 🌍 Другие города.", {}),
    "city_shops": ("Над списком магазинов выбранного города.", {"город": "название города"}),
    "empty": ("Добавляется к экрану, когда в городе или подборке ещё нет магазинов.", {}),
    "search_prompt": ("Приглашение написать запрос после нажатия 🔍 Поиск.", {}),
    "search_results": ("Над найденными магазинами.", {"запрос": "то, что искал пользователь"}),
    "search_empty": ("Когда поиск ничего не нашёл.", {"запрос": "то, что искал пользователь"}),
    "report_prompt": ("После нажатия 🚩 Пожаловаться в карточке.", {"магазин": "название магазина"}),
    "report_thanks": ("После отправки жалобы.", {}),
    "report_limit": ("Всплывает, если пользователь жалуется слишком часто.", {}),
    "verified_badge": ("Вверху карточки магазина с отметкой Проверенный.", {}),
    "banned": ("Всплывает у забаненного пользователя.", {}),
    "flood": ("Всплывает, когда пользователь жмёт кнопки слишком быстро.", {}),
    "shop_unavailable": ("Всплывает, если магазин скрыли, а у человека осталась старая кнопка.", {}),
    "city_categories": ("Над кнопками категорий после выбора города.", {"город": "название города"}),
    "city_category_shops": ("Над магазинами выбранной категории в городе.",
                            {"город": "название города", "категория": "название категории"}),
    "categories": ("Экран кнопки меню Категории, если у самой кнопки текст пустой.", {}),
    "category_shops": ("Над магазинами категории по всем городам.", {"категория": "название категории"}),
    "favorites": ("Над списком избранного (если текст у кнопки меню пустой).", {}),
    "favorites_empty": ("Когда в избранном ничего нет.", {}),
    "fav_added": ("Всплывает после нажатия ⭐ В избранное.", {}),
    "fav_removed": ("Всплывает после нажатия Из избранного.", {}),
    "language": ("Экран выбора языка (если текст у кнопки меню пустой).", {}),
    "apply_intro": ("Первый экран заявки на размещение магазина.", {}),
    "apply_step": ("Над каждым вопросом анкеты.", {"шаг": "номер вопроса", "всего": "сколько всего вопросов"}),
    "apply_wrong": ("Если прислали не то (например, текст вместо фото).", {}),
    "apply_confirm": ("Заголовок сводки ответов перед отправкой.", {}),
    "apply_done": ("После отправки заявки.", {}),
    "apply_pending": ("Если у человека уже есть заявка на рассмотрении.", {}),
    "apply_cooldown": ("Если новую заявку отправляют слишком скоро.", {}),
    "apply_accepted": ("Приходит автору, когда заявку одобрили.", {}),
    "apply_rejected": ("Приходит автору, когда заявку отклонили.", {"причина": "причина, которую вы укажете"}),
    "moderator_message": ("Так выглядит ваш ответ автору заявки.", {"текст": "ваше сообщение"}),
    "card_cities": ("Строка под описанием магазина. Бот сам собирает её из городов магазина.",
                    {"города": "список городов через запятую"}),
    "card_cities_all": ("Показывается вместо списка, если магазин отмечен во всех городах.", {}),
    "contact_greeting": ("Покупатель жмёт кнопку-контакт оператора, и в чате с оператором уже вписан этот текст. "
                         "Человек сам нажимает Отправить. Работает для ссылок на @username. "
                         "Форматирование здесь не поддерживается, только текст и обычные эмодзи. "
                         "Оставьте текст пустым, чтобы отключить.", {}),
}
BUTTON_NAMES = {
    "back": "◀️ Назад",
    "prev": "◀️ Предыдущая страница",
    "next": "▶️ Следующая страница",
    "other_cities": "🌍 Другие города",
    "report": "🚩 Пожаловаться",
    "all_shops": "📋 Все магазины города",
    "operator": "👤 Кнопка связи с продавцом (подпись по умолчанию)",
    "fav_add": "⭐ В избранное",
    "fav_remove": "✖️ Из избранного",
    "share": "📤 Поделиться магазином",
    "apply_start": "📝 Заполнить заявку",
    "apply_skip": "⏭ Пропустить вопрос",
    "apply_send": "✅ Отправить заявку",
    "apply_restart": "✏️ Заполнить заново",
    "apply_cancel": "✖️ Отмена заявки",
}
MEDIA_TEXTS = {"cities", "other_cities", "city_shops", "city_categories", "search_prompt"}


# Тексты и кнопки разложены по темам: (название, описание, тексты, кнопки)
TEXT_GROUPS = [
    ("🏙 Города и списки", "Экраны городов, категорий и списков магазинов.",
     ["other_cities", "city_shops", "city_categories", "city_category_shops", "categories", "category_shops",
      "cities", "empty"], ["other_cities", "all_shops"]),
    ("🏪 Карточка магазина", "Всё, что видно в карточке и под ней.",
     ["verified_badge", "card_cities", "card_cities_all", "contact_greeting", "shop_unavailable"],
     ["operator", "fav_add", "fav_remove", "share", "report"]),
    ("🔍 Поиск", "", ["search_prompt", "search_results", "search_empty"], []),
    ("⭐ Избранное", "", ["favorites", "favorites_empty", "fav_added", "fav_removed"], []),
    ("🚩 Жалобы", "", ["report_prompt", "report_thanks", "report_limit"], []),
    ("📝 Заявка на размещение", "Анкета для продавцов и ответы им.",
     ["apply_intro", "apply_step", "apply_wrong", "apply_confirm", "apply_done", "apply_pending", "apply_cooldown",
      "apply_accepted", "apply_rejected", "moderator_message"],
     ["apply_start", "apply_skip", "apply_send", "apply_restart", "apply_cancel"]),
    ("◀️ Назад и страницы", "Кнопки, которые есть почти на каждом экране.", [], ["back", "prev", "next"]),
    ("🛡 Служебные", "Сообщения при бане, флуде и выборе языка.", ["banned", "flood", "language"], []),
]


def group_of(kind: str, key: str) -> int:
    """В какой теме лежит текст или кнопка, чтобы «Назад» вёл обратно в неё."""
    for i, (_, _, texts, btns) in enumerate(TEXT_GROUPS):
        if key in (texts if kind == "text" else btns):
            return i
    return -1


@view("texts", "texts")
async def view_texts(ctx: Ctx) -> ViewResult:
    cat = ctx.app.catalog
    rows: Rows = [[b("👋 Приветствие (главный экран)", f"a:item:{cat.root_id}")]]
    rows += grid([b(title, f"a:txg:{i}") for i, (title, _, _, _) in enumerate(TEXT_GROUPS)], 2)
    rows.append(back_btn("a:cfg"))
    html = ("📝 <b>Тексты и кнопки</b>\n\n"
            "Выберите тему. Внутри каждого текста написано, где он показывается.\n"
            "Слова в фигурных скобках бот заменяет сам: <code>{имя}</code> на имя пользователя, "
            "<code>{город}</code> на название города.")
    return html, rows


@view("txg", "texts")
async def view_text_group(ctx: Ctx, idx: str) -> ViewResult:
    cat = ctx.app.catalog
    if not idx.isdigit() or int(idx) >= len(TEXT_GROUPS):
        return await view_texts(ctx)
    title, about, texts, btns = TEXT_GROUPS[int(idx)]
    rows: Rows = [[b(TEXT_NAMES[k], f"a:text:{k}")] for k in texts if k in cat.texts and k in TEXT_NAMES]
    if btns:
        rows += grid([b(f"🔘 {BUTTON_NAMES[k]}", f"a:btn:{k}") for k in btns if k in cat.buttons], 2)
    rows.append(back_btn("a:texts"))
    html = f"<b>{title}</b>" + (f"\n{about}" if about else "")
    if texts and btns:
        html += "\n\nСверху тексты, ниже 🔘 кнопки."
    return html, rows


@view("text", "texts")
async def view_text(ctx: Ctx, key: str) -> ViewResult:
    app = ctx.app
    row = await app.db.fetchone("SELECT * FROM texts WHERE key = ?", (key,))
    if row is None:
        return await view_texts(ctx)
    where, subs = TEXT_HELP.get(key, ("", {}))
    subs_line = ""
    if subs:
        subs_line = "Можно вставить: " + ", ".join(
            f"<code>{{{k}}}</code> ({v})" for k, v in subs.items()) + "\n"
    html = (f"📝 <b>{TEXT_NAMES.get(key, 'Текст')}</b>\n"
            f"<i>{where}</i>\n{subs_line}"
            f"Медиа: {media_line(app, row['media_id'])}\n\n"
            f"<b>Сейчас так:</b>\n\n{row['html'] or '<i>пусто</i>'}")
    rows = editor_rows("text", key, row, label=False, rich=True, app=app)
    if key not in MEDIA_TEXTS:  # медиа уместно только у экранов
        rows = [[b("📝 Изменить текст", f"x:htm:text:{key}")],
                [b("🌐 Перевод на другие языки", f"a:trl:text:{key}")]]
    g = group_of("text", key)
    rows.append(back_btn(f"a:txg:{g}" if g >= 0 else "a:texts"))
    return html, rows


@view("btn", "texts")
async def view_button(ctx: Ctx, key: str) -> ViewResult:
    row = await ctx.app.db.fetchone("SELECT * FROM buttons WHERE key = ?", (key,))
    if row is None:
        return await view_texts(ctx)
    html = (f"🔘 <b>{BUTTON_NAMES.get(key, 'Кнопка')}</b>\n\n"
            f"Текст: {escape(row['label'])}\n"
            f"Иконка: {icon_line(row['icon'])}\n"
            f"Цвет: {style_name(row['style'])}\n\n"
            "Так она выглядит 👇")
    rows = [[button(row["label"], row["icon"], row["style"], cb="noop")]]
    rows += editor_rows("btn", key, row, label=True, rich=False)
    g = group_of("btn", key)
    rows.append([b("◀️ Назад", f"a:txg:{g}" if g >= 0 else "a:texts"),
                 b("📋 Главное меню", f"a:item:{ctx.app.catalog.root_id}")])
    return html, rows


# ---------- города ----------
@view("cities", "cities")
async def view_cities(ctx: Ctx, page: str = "0") -> ViewResult:
    cat = ctx.app.catalog
    cities = sorted(cat.cities.values(), key=lambda c: (not c.is_main, c.position, c.id))
    chunk, p, pages = paginate(cities, int(page), 30)
    rows = grid([b(("⭐️ " if c.is_main else "") + ("🙈 " if not c.is_active else "") + c.label, f"a:city:{c.id}")
                 for c in chunk], 2)
    nav = []
    if p > 0:
        nav.append(b("◀️", f"a:cities:{p - 1}"))
    if pages > 1:
        nav.append(button(f"{p + 1}/{pages}", cb="noop"))
    if p < pages - 1:
        nav.append(b("▶️", f"a:cities:{p + 1}"))
    rows.append(nav)
    rows.append([b("➕ Добавить города", "x:cnew", "success")])
    rows.append(back_btn("a:cfg"))
    html = ("🏙 <b>Города</b>\n\n⭐️ Главные: показываются прямо в главном меню.\n"
            "Остальные собраны под кнопкой 🌍 Другие города. Там сразу список магазинов из этих городов, "
            "а сам город написан в карточке магазина.\n🙈 Скрытые.")
    return html, rows


@action("cnew", "cities")
async def act_city_new(ctx: Ctx):
    return await ctx.ask("cnew", "Отправьте название города. Можно сразу несколько, каждый с новой строки.", "a:cities:0")


@on_input("cnew", "cities")
async def in_city_new(ctx: Ctx, message: Message):
    names = [" ".join(n.split())[:64] for n in (message.text or "").split("\n") if n.strip()]
    if not names:
        raise InputError("Нужен текст.")
    db = ctx.app.db
    pos = (await db.fetchval("SELECT COALESCE(MAX(position), -1) + 1 FROM cities WHERE is_main = 0")) or 0
    await db.executemany("INSERT INTO cities(label, is_main, position) VALUES (?, 0, ?)",
                         ((n, pos + i) for i, n in enumerate(names)))
    await ctx.reload()
    await ctx.log("city.create", ", ".join(names))
    ctx.notice = f"✅ Добавлено городов: {len(names)}"
    return "a:cities:0"


@view("city", "cities")
async def view_city(ctx: Ctx, city_id: str) -> ViewResult:
    app = ctx.app
    row = await app.db.fetchone("SELECT * FROM cities WHERE id = ?", (int(city_id),))
    if row is None:
        return await view_cities(ctx)
    shops = len(app.catalog.by_city.get(row["id"], []))
    html = (f"🏙 <b>{escape(row['label'])}</b>\n"
            f"Главный: {'⭐️ да' if row['is_main'] else 'нет, в разделе Другие города'}\n"
            f"Статус: {'виден' if row['is_active'] else '🙈 скрыт'}\n"
            f"Иконка: {icon_line(row['icon'])}\n"
            f"Магазинов: {shops}")
    rows = editor_rows("city", city_id, row, label=True, rich=False)
    rows.append([b("✖️ Убрать из главных" if row["is_main"] else "⭐️ Сделать главным", f"x:cmain:{city_id}")])
    rows.append([b("⬆️ Выше", f"x:cmv:{city_id}:-1"), b("⬇️ Ниже", f"x:cmv:{city_id}:1")])
    rows.append([b("🙈 Скрыть" if row["is_active"] else "👁 Показать", f"x:cact:{city_id}"),
                 b("🗑 Удалить", f"a:cdel:{city_id}", "danger")])
    rows.append([b("◀️ Все города", "a:cities:0"), b("📋 Главное меню", f"a:item:{app.catalog.root_id}")])
    return html, rows


@action("cmain", "cities")
async def act_city_main(ctx: Ctx, city_id: str):
    db = ctx.app.db
    pos = await db.fetchval(
        "SELECT COALESCE(MAX(position), -1) + 1 FROM cities WHERE is_main = 1 - (SELECT is_main FROM cities WHERE id = ?)",
        (int(city_id),))
    await db.execute("UPDATE cities SET is_main = 1 - is_main, position = ? WHERE id = ?", (pos, int(city_id)))
    await ctx.reload()
    return f"a:city:{city_id}"


@action("cmv", "cities")
async def act_city_move(ctx: Ctx, city_id: str, delta: str):
    is_main = await ctx.app.db.fetchval("SELECT is_main FROM cities WHERE id = ?", (int(city_id),))
    await move(ctx, "cities", int(city_id), int(delta), "is_main = ?", (is_main,))
    return f"a:city:{city_id}"


@action("cact", "cities")
async def act_city_active(ctx: Ctx, city_id: str):
    await ctx.app.db.execute("UPDATE cities SET is_active = 1 - is_active WHERE id = ?", (int(city_id),))
    await ctx.reload()
    return f"a:city:{city_id}"


@view("cdel", "cities")
async def view_city_delete(ctx: Ctx, city_id: str) -> ViewResult:
    city = ctx.app.catalog.cities.get(int(city_id))
    return (f"🗑 Удалить город <b>{escape(city.label if city else city_id)}</b>? Магазины останутся, "
            "но отвяжутся от этого города.",
            [[b("🗑 Да, удалить", f"x:cdel:{city_id}", "danger"), b("✖️ Отмена", f"a:city:{city_id}")]])


@action("cdel", "cities")
async def act_city_delete(ctx: Ctx, city_id: str):
    city = ctx.app.catalog.cities.get(int(city_id))
    await ctx.app.db.execute("DELETE FROM cities WHERE id = ?", (int(city_id),))
    await ctx.reload()
    await ctx.log("city.delete", city.label if city else city_id)
    ctx.notice = "🗑 Город удалён."
    return "a:cities:0"


# ---------- метки ----------
@view("tags", "cities")
async def view_tags(ctx: Ctx) -> ViewResult:
    cat = ctx.app.catalog
    rows: Rows = [[b(f"{t.label} · {len(cat.by_tag.get(t.id, []))}", f"a:tag:{t.id}")] for t in cat.tags.values()]
    rows.append([b("➕ Новая метка", "x:tnew", "success")])
    rows.append(back_btn("a:cfg"))
    html = ("🏷 <b>Метки</b>\n\n"
            "Метка это подборка магазинов: Премиум, Топ и другие. Порядок меток задаёт приоритет: "
            "в списках городов магазины с верхней меткой идут первыми.\n"
            "Чтобы метка появилась в меню, откройте её и нажмите ➕ Добавить кнопку в главное меню.")
    return html, rows


@action("tnew", "cities")
async def act_tag_new(ctx: Ctx):
    return await ctx.ask("tnew", "Отправьте название метки, например: Новинки.", "a:tags")


@on_input("tnew", "cities")
async def in_tag_new(ctx: Ctx, message: Message):
    label, _ = parse_label(message)
    if not label:
        raise InputError("Нужен текст.")
    db = ctx.app.db
    pos = (await db.fetchval("SELECT COALESCE(MAX(position), -1) + 1 FROM tags")) or 0
    tag_id = await db.execute("INSERT INTO tags(label, position) VALUES (?, ?)", (label, pos))
    await ctx.reload()
    await ctx.log("tag.create", label)
    return f"a:tag:{tag_id}"


@view("tag", "cities")
async def view_tag(ctx: Ctx, tag_id: str) -> ViewResult:
    cat = ctx.app.catalog
    tag = cat.tags.get(int(tag_id))
    if tag is None:
        return await view_tags(ctx)
    used = [i.label for i in cat.menu.values() if i.kind == "tag" and i.payload == str(tag.id)]
    html = (f"🏷 <b>{escape(tag.label)}</b>\n"
            f"Магазинов: {len(cat.by_tag.get(tag.id, []))}\n"
            f"Кнопки меню: {escape(', '.join(used)) or 'нет'}")
    rows: Rows = []
    if not used:
        rows.append([b("➕ Добавить кнопку в главное меню", f"x:tagbtn:{tag_id}", "success")])
    rows += [
        [b("✏️ Переименовать", f"x:lbl:tag:{tag_id}")],
        [b("⬆️ Приоритет выше", f"x:tmv:{tag_id}:-1"), b("⬇️ Ниже", f"x:tmv:{tag_id}:1")],
        [b("🗑 Удалить", f"a:tdel:{tag_id}", "danger")],
        back_btn("a:tags"),
    ]
    return html, rows


@action("tagbtn", "cities")
async def act_tag_menu_button(ctx: Ctx, tag_id: str):
    """Кнопка подборки в главном меню одним нажатием: магазины с меткой появятся там сами."""
    cat = ctx.app.catalog
    tag = cat.tags.get(int(tag_id))
    if tag is None:
        return "a:tags"
    db = ctx.app.db
    row = await db.fetchval("SELECT COALESCE(MAX(row), -1) + 1 FROM menu_items WHERE parent_id = ?", (cat.root_id,))
    item_id = await db.execute(
        "INSERT INTO menu_items(parent_id, kind, payload, label, html, row, position) VALUES (?, 'tag', ?, ?, ?, ?, 0)",
        (cat.root_id, str(tag.id), tag.label, f"<b>{escape(tag.label)}</b>", row))
    await ctx.reload()
    await ctx.log("menu.create", f"{item_id}: {tag.label}")
    ctx.notice = ("✅ Кнопка добавлена в главное меню (внизу). Все магазины с этой меткой появятся в ней сами. "
                  "Здесь можно поменять эмодзи, цвет и место кнопки.")
    return f"a:item:{item_id}"


@action("tmv", "cities")
async def act_tag_move(ctx: Ctx, tag_id: str, delta: str):
    await move(ctx, "tags", int(tag_id), int(delta))
    return f"a:tag:{tag_id}"


@view("tdel", "cities")
async def view_tag_delete(ctx: Ctx, tag_id: str) -> ViewResult:
    tag = ctx.app.catalog.tags.get(int(tag_id))
    return (f"🗑 Удалить метку <b>{escape(tag.label if tag else tag_id)}</b>? Она снимется со всех магазинов.",
            [[b("🗑 Да, удалить", f"x:tdel:{tag_id}", "danger"), b("✖️ Отмена", f"a:tag:{tag_id}")]])


@action("tdel", "cities")
async def act_tag_delete(ctx: Ctx, tag_id: str):
    await ctx.app.db.execute("DELETE FROM tags WHERE id = ?", (int(tag_id),))
    await ctx.reload()
    await ctx.log("tag.delete", tag_id)
    return "a:tags"


# ---------- категории ----------
@view("catgs", "cities")
async def view_categories(ctx: Ctx) -> ViewResult:
    cat = ctx.app.catalog
    rows = grid([b(("🙈 " if not c.is_active else "") + f"{c.label} · {len(cat.by_category.get(c.id, []))}",
                   f"a:catg:{c.id}") for c in cat.categories.values()], 2)
    rows.append([b("➕ Добавить категории", "x:catnew", "success")])
    rows.append([b(f"🏙 Категории внутри города: {'вкл' if cat.setting('city_categories', 1) else 'выкл'}",
                   "x:cattog")])
    rows.append([b(f"Показывать категории, если в городе больше {cat.setting('city_categories_min', 6)} магазинов",
                   "x:catmin")])
    rows.append(back_btn("a:cfg"))
    html = ("🗂 <b>Категории</b> (VPN, подарки, звёзды…)\n\n"
            "Магазину можно поставить несколько категорий: карточка магазина, затем 🗂 Категории.\n"
            "Когда категории внутри города включены, после выбора города человек сначала видит категории, "
            "в которых в этом городе есть магазины, и кнопку 📋 Все магазины. Если магазинов в городе мало, "
            "категории не показываются, сразу открывается список.\n"
            "Ещё можно добавить в меню кнопку типа 🗂 Категории, она покажет категории по всем городам.")
    return html, rows


@action("cattog", "cities")
async def act_city_categories_toggle(ctx: Ctx):
    value = 0 if ctx.app.catalog.setting("city_categories", 1) else 1
    await ctx.app.db.execute("INSERT OR REPLACE INTO settings(key, value) VALUES ('city_categories', ?)", (str(value),))
    await ctx.reload()
    return "a:catgs"


@action("catmin", "cities")
async def act_categories_min(ctx: Ctx):
    return await ctx.ask("catmin", "Сколько магазинов должно быть в городе, чтобы показывать категории? "
                                   "Если меньше или столько же, откроется сразу список магазинов. Отправьте число, "
                                   "например 6. 0 значит показывать категории всегда.", "a:catgs")


@on_input("catmin", "cities")
async def in_categories_min(ctx: Ctx, message: Message):
    text = (message.text or "").strip()
    if not text.isdigit() or int(text) > 1000:
        raise InputError("Нужно число от 0 до 1000.")
    await ctx.app.db.execute("INSERT OR REPLACE INTO settings(key, value) VALUES ('city_categories_min', ?)", (text,))
    await ctx.reload()
    await ctx.log("settings", f"city_categories_min={text}")
    return "a:catgs"


@action("catnew", "cities")
async def act_category_new(ctx: Ctx):
    return await ctx.ask("catnew", "Отправьте название категории. Можно сразу несколько, каждую с новой строки.\n"
                                   "Премиум-эмодзи в начале станет иконкой кнопки.", "a:catgs")


@on_input("catnew", "cities")
async def in_category_new(ctx: Ctx, message: Message):
    names = [" ".join(n.split())[:64] for n in (message.text or "").split("\n") if n.strip()]
    if not names:
        raise InputError("Нужен текст.")
    db = ctx.app.db
    pos = (await db.fetchval("SELECT COALESCE(MAX(position), -1) + 1 FROM categories")) or 0
    if len(names) == 1:  # одна категория — можно с премиум-иконкой
        label, icon = parse_label(message)
        cat_id = await db.execute("INSERT INTO categories(label, icon, position) VALUES (?, ?, ?)", (label, icon, pos))
        await ctx.reload()
        await ctx.log("cat.create", label)
        return f"a:catg:{cat_id}"
    await db.executemany("INSERT INTO categories(label, position) VALUES (?, ?)",
                         ((n, pos + i) for i, n in enumerate(names)))
    await ctx.reload()
    await ctx.log("cat.create", ", ".join(names))
    ctx.notice = f"✅ Добавлено категорий: {len(names)}"
    return "a:catgs"


@view("catg", "cities")
async def view_category(ctx: Ctx, cat_id: str) -> ViewResult:
    app = ctx.app
    row = await app.db.fetchone("SELECT * FROM categories WHERE id = ?", (int(cat_id),))
    if row is None:
        return await view_categories(ctx)
    html = (f"🗂 <b>{escape(row['label'])}</b>\n"
            f"Статус: {'видна' if row['is_active'] else '🙈 скрыта'}\n"
            f"Иконка: {icon_line(row['icon'])}\n"
            f"Магазинов: {len(app.catalog.by_category.get(row['id'], []))}")
    rows = editor_rows("cat", cat_id, row, label=True, rich=False)
    rows.append([b("⬆️ Выше", f"x:catmv:{cat_id}:-1"), b("⬇️ Ниже", f"x:catmv:{cat_id}:1")])
    rows.append([b("🙈 Скрыть" if row["is_active"] else "👁 Показать", f"x:catact:{cat_id}"),
                 b("🗑 Удалить", f"a:catdel:{cat_id}", "danger")])
    rows.append(back_btn("a:catgs"))
    return html, rows


@action("catmv", "cities")
async def act_category_move(ctx: Ctx, cat_id: str, delta: str):
    await move(ctx, "categories", int(cat_id), int(delta))
    return f"a:catg:{cat_id}"


@action("catact", "cities")
async def act_category_active(ctx: Ctx, cat_id: str):
    await ctx.app.db.execute("UPDATE categories SET is_active = 1 - is_active WHERE id = ?", (int(cat_id),))
    await ctx.reload()
    return f"a:catg:{cat_id}"


@view("catdel", "cities")
async def view_category_delete(ctx: Ctx, cat_id: str) -> ViewResult:
    c = ctx.app.catalog.categories.get(int(cat_id))
    return (f"🗑 Удалить категорию <b>{escape(c.label if c else cat_id)}</b>? Магазины останутся.",
            [[b("🗑 Да, удалить", f"x:catdel:{cat_id}", "danger"), b("✖️ Отмена", f"a:catg:{cat_id}")]])


@action("catdel", "cities")
async def act_category_delete(ctx: Ctx, cat_id: str):
    c = ctx.app.catalog.categories.get(int(cat_id))
    await ctx.app.db.execute("DELETE FROM categories WHERE id = ?", (int(cat_id),))
    await ctx.reload()
    await ctx.log("cat.delete", c.label if c else cat_id)
    return "a:catgs"
