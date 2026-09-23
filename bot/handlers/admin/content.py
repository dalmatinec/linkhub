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
    "other_cities": "🌍 Экран «Другие города»",
    "city_shops": "🏙 Список магазинов города",
    "empty": "📭 Когда в списке пусто",
    "search_prompt": "🔍 Приглашение к поиску",
    "search_results": "🔍 Результаты поиска",
    "search_empty": "🔍 Ничего не найдено",
    "report_prompt": "🚩 Просьба описать жалобу",
    "report_thanks": "🚩 Спасибо за жалобу",
    "report_limit": "🚩 Слишком частые жалобы",
    "verified_badge": "✅ Плашка «Проверенный магазин»",
    "banned": "🚫 Сообщение забаненному",
    "flood": "🐢 «Слишком быстро» (антифлуд)",
    "shop_unavailable": "🙈 Магазин недоступен",
    "city_categories": "🗂 Категории внутри города",
    "city_category_shops": "🗂 Магазины города в категории",
    "categories": "🗂 Экран «Категории»",
    "category_shops": "🗂 Магазины категории",
    "favorites": "⭐ Заголовок «Избранное»",
    "favorites_empty": "⭐ Пустое избранное",
    "fav_added": "⭐ «Добавлено в избранное»",
    "fav_removed": "⭐ «Убрано из избранного»",
    "language": "🌐 Экран выбора языка",
    "apply_intro": "📝 Заявка: вступление",
    "apply_step": "📝 Заявка: «Шаг N из M»",
    "apply_wrong": "📝 Заявка: неверный ответ",
    "apply_confirm": "📝 Заявка: проверка перед отправкой",
    "apply_done": "📝 Заявка: отправлена",
    "apply_pending": "📝 Заявка: уже на рассмотрении",
    "apply_cooldown": "📝 Заявка: слишком часто",
    "apply_accepted": "📝 Заявка одобрена (сообщение автору)",
    "apply_rejected": "📝 Заявка отклонена (сообщение автору)",
    "moderator_message": "💬 Сообщение модератора автору заявки",
}
# Где показывается текст и что в него можно подставить
TEXT_HELP = {
    "cities": ("Над кнопками городов после нажатия «Выбрать город».", {}),
    "other_cities": ("Над списком городов после нажатия «Другие города».", {}),
    "city_shops": ("Над списком магазинов выбранного города.", {"город": "название города"}),
    "empty": ("Добавляется к экрану, когда в городе или подборке ещё нет магазинов.", {}),
    "search_prompt": ("После нажатия «Поиск» — приглашение написать запрос.", {}),
    "search_results": ("Над найденными магазинами.", {"запрос": "то, что искал пользователь"}),
    "search_empty": ("Когда поиск ничего не нашёл.", {"запрос": "то, что искал пользователь"}),
    "report_prompt": ("После нажатия «Пожаловаться» в карточке.", {"магазин": "название магазина"}),
    "report_thanks": ("После отправки жалобы.", {}),
    "report_limit": ("Всплывает, если пользователь жалуется слишком часто.", {}),
    "verified_badge": ("Сверху карточки магазина с отметкой «Проверенный».", {}),
    "banned": ("Всплывает у забаненного пользователя.", {}),
    "flood": ("Всплывает, когда пользователь жмёт кнопки слишком быстро.", {}),
    "shop_unavailable": ("Всплывает, если магазин скрыли, а у человека осталась старая кнопка.", {}),
    "city_categories": ("Над кнопками категорий после выбора города.", {"город": "название города"}),
    "city_category_shops": ("Над магазинами выбранной категории в городе.",
                            {"город": "название города", "категория": "название категории"}),
    "categories": ("Экран кнопки меню «Категории» (если текст у самой кнопки пустой).", {}),
    "category_shops": ("Над магазинами категории по всем городам.", {"категория": "название категории"}),
    "favorites": ("Над списком избранного (если текст у кнопки меню пустой).", {}),
    "favorites_empty": ("Когда в избранном ничего нет.", {}),
    "fav_added": ("Всплывает после нажатия «В избранное».", {}),
    "fav_removed": ("Всплывает после «Из избранного».", {}),
    "language": ("Экран выбора языка (если текст у кнопки меню пустой).", {}),
    "apply_intro": ("Первый экран заявки «Разместить магазин».", {}),
    "apply_step": ("Над каждым вопросом анкеты.", {"шаг": "номер вопроса", "всего": "сколько всего вопросов"}),
    "apply_wrong": ("Если прислали не то (например, текст вместо фото).", {}),
    "apply_confirm": ("Заголовок сводки ответов перед отправкой.", {}),
    "apply_done": ("После отправки заявки.", {}),
    "apply_pending": ("Если у человека уже есть заявка на рассмотрении.", {}),
    "apply_cooldown": ("Если новую заявку отправляют слишком скоро.", {}),
    "apply_accepted": ("Приходит автору, когда заявку одобрили.", {}),
    "apply_rejected": ("Приходит автору, когда заявку отклонили.", {"причина": "причина, которую вы укажете"}),
    "moderator_message": ("Так выглядит ваш ответ автору заявки.", {"текст": "ваше сообщение"}),
}
BUTTON_NAMES = {
    "back": "◀️ Назад",
    "prev": "◀️ Предыдущая страница",
    "next": "▶️ Следующая страница",
    "other_cities": "🌍 Другие города",
    "report": "🚩 Пожаловаться",
    "all_shops": "📋 Все магазины города",
    "fav_add": "⭐ В избранное",
    "fav_remove": "✖️ Из избранного",
    "apply_start": "📝 Заполнить заявку",
    "apply_skip": "⏭ Пропустить вопрос",
    "apply_send": "✅ Отправить заявку",
    "apply_restart": "✏️ Заполнить заново",
    "apply_cancel": "✖️ Отмена заявки",
}
MEDIA_TEXTS = {"cities", "other_cities", "city_shops", "city_categories", "search_prompt"}


@view("texts", "texts")
async def view_texts(ctx: Ctx) -> ViewResult:
    cat = ctx.app.catalog
    rows: Rows = [[b("👋 Приветствие (/start)", f"a:item:{cat.root_id}")]]
    rows += [[b(TEXT_NAMES[k], f"a:text:{k}")] for k in TEXT_NAMES if k in cat.texts]
    rows.append([button("— Системные кнопки —", cb="noop")])
    rows += grid([b(BUTTON_NAMES[k], f"a:btn:{k}") for k in BUTTON_NAMES if k in cat.buttons], 2)
    rows.append(back_btn("a:home"))
    html = ("📝 <b>Тексты и кнопки</b>\n\n"
            "Выберите, что изменить. Внутри каждого текста написано, где он показывается.\n"
            "Слова в фигурных скобках бот заменяет сам: <code>{имя}</code> — имя пользователя, "
            "<code>{город}</code> — название города.")
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
            f"<code>{{{k}}}</code> — {v}" for k, v in subs.items()) + "\n"
    html = (f"📝 <b>{TEXT_NAMES.get(key, 'Текст')}</b>\n"
            f"<i>{where}</i>\n{subs_line}"
            f"Медиа: {media_line(app, row['media_id'])}\n\n"
            f"<b>Сейчас так:</b>\n\n{row['html'] or '<i>пусто</i>'}")
    rows = editor_rows("text", key, row, label=False, rich=True)
    if key not in MEDIA_TEXTS:  # медиа уместно только у экранов
        rows = [[b("📝 Изменить текст", f"x:htm:text:{key}")],
                [b("🌐 Перевод на другие языки", f"a:trl:text:{key}")]]
    rows.append(back_btn("a:texts"))
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
    rows.append(back_btn("a:texts"))
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
    rows.append(back_btn("a:home"))
    html = ("🏙 <b>Города</b>\n\n⭐️ — главные: показываются сразу на экране выбора города, "
            "остальные — под кнопкой «Другие города».\n🙈 — скрытые.")
    return html, rows


@action("cnew", "cities")
async def act_city_new(ctx: Ctx):
    return await ctx.ask("cnew", "Отправьте название города. Можно несколько — каждый с новой строки.", "a:cities:0")


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
            f"Главный: {'⭐️ да' if row['is_main'] else 'нет (в «Других городах»)'}\n"
            f"Статус: {'виден' if row['is_active'] else '🙈 скрыт'}\n"
            f"Иконка: {icon_line(row['icon'])}\n"
            f"Магазинов: {shops}")
    rows = editor_rows("city", city_id, row, label=True, rich=False)
    rows.append([b("✖️ Убрать из главных" if row["is_main"] else "⭐️ Сделать главным", f"x:cmain:{city_id}")])
    rows.append([b("⬆️ Выше", f"x:cmv:{city_id}:-1"), b("⬇️ Ниже", f"x:cmv:{city_id}:1")])
    rows.append([b("🙈 Скрыть" if row["is_active"] else "👁 Показать", f"x:cact:{city_id}"),
                 b("🗑 Удалить", f"a:cdel:{city_id}", "danger")])
    rows.append(back_btn("a:cities:0"))
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
    rows.append(back_btn("a:home"))
    html = ("🏷 <b>Метки</b>\n\n"
            "Метка — это подборка магазинов (Премиум, Топ…). Порядок меток = приоритет: "
            "в списках городов магазины с верхней меткой идут первыми.\n"
            "Чтобы метка появилась в меню, добавьте в «Меню» кнопку типа «Магазины с меткой».")
    return html, rows


@action("tnew", "cities")
async def act_tag_new(ctx: Ctx):
    return await ctx.ask("tnew", "Отправьте название метки (например, «Новинки»).", "a:tags")


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
    rows: Rows = [
        [b("✏️ Переименовать", f"x:lbl:tag:{tag_id}")],
        [b("⬆️ Приоритет выше", f"x:tmv:{tag_id}:-1"), b("⬇️ Ниже", f"x:tmv:{tag_id}:1")],
        [b("🗑 Удалить", f"a:tdel:{tag_id}", "danger")],
        back_btn("a:tags"),
    ]
    return html, rows


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
    rows.append(back_btn("a:home"))
    html = ("🗂 <b>Категории</b> (VPN, подарки, звёзды…)\n\n"
            "Магазину можно поставить несколько категорий (в карточке магазина → «🗂 Категории»).\n"
            "Когда «Категории внутри города» включены, после выбора города человек сначала видит категории, "
            "в которых в этом городе есть магазины, и кнопку «Все магазины».\n"
            "Можно также добавить в меню кнопку типа «🗂 Категории» — категории по всем городам.")
    return html, rows


@action("cattog", "cities")
async def act_city_categories_toggle(ctx: Ctx):
    value = 0 if ctx.app.catalog.setting("city_categories", 1) else 1
    await ctx.app.db.execute("INSERT OR REPLACE INTO settings(key, value) VALUES ('city_categories', ?)", (str(value),))
    await ctx.reload()
    return "a:catgs"


@action("catnew", "cities")
async def act_category_new(ctx: Ctx):
    return await ctx.ask("catnew", "Отправьте название категории. Можно несколько — каждую с новой строки.\n"
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
