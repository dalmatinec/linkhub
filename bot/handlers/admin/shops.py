"""Админка: магазины."""
import time
from datetime import datetime, timedelta, timezone
from html import escape

from aiogram.types import Message

from ...catalog import Shop, now
from ...richtext import parse_contacts, parse_label
from ...ui import button, grid, paginate
from ..user import screen_card
from .core import (
    Ctx, InputError, Rows, ViewResult, action, b, back_btn, editor_rows, icon_line, media_line, move, on_input,
    snippet, view,
)

P = "shops"


def fmt_date(ts: int | None, tz: int) -> str:
    if not ts:
        return "бессрочно"
    return datetime.fromtimestamp(ts, timezone(timedelta(hours=tz))).strftime("%d.%m.%Y %H:%M")


def shop_title(shop: Shop) -> str:
    return ("" if shop.is_active else "🙈 ") + shop.label


def sorted_shops(ctx: Ctx) -> list[Shop]:
    cat = ctx.app.catalog
    return sorted(cat.shops.values(), key=cat.shop_rank)


@view("shops", P)
async def view_shops(ctx: Ctx, page: str = "0") -> ViewResult:
    shops = sorted_shops(ctx)
    chunk, p, pages = paginate(shops, int(page), 20)
    rows = grid([b(shop_title(s), f"a:shop:{s.id}") for s in chunk], 2)
    nav = []
    if p > 0:
        nav.append(b("◀️", f"a:shops:{p - 1}"))
    if pages > 1:
        nav.append(button(f"{p + 1}/{pages}", cb="noop"))
    if p < pages - 1:
        nav.append(b("▶️", f"a:shops:{p + 1}"))
    rows.append(nav)
    rows.append([b("➕ Добавить", "x:shopnew", "success"), b("🔍 Найти", "x:shopfind")])
    show_cities = ctx.app.catalog.setting("card_show_cities", 1)
    rows.append([b(f"🏙 Города в карточке: {'показывать' if show_cities else 'не показывать'}", "x:cardcity")])
    rows.append(back_btn("a:home"))
    html = f"🏪 <b>Магазины</b> — {len(shops)}\n🙈 — скрытые (не видны пользователям)"
    return html, rows


@action("cardcity", P)
async def act_card_cities_toggle(ctx: Ctx):
    value = 0 if ctx.app.catalog.setting("card_show_cities", 1) else 1
    await ctx.app.db.execute("INSERT OR REPLACE INTO settings(key, value) VALUES ('card_show_cities', ?)", (str(value),))
    await ctx.reload()
    return "a:shops:0"


@action("shopnew", P)
async def act_shop_new(ctx: Ctx):
    return await ctx.ask(
        "shopnew",
        "Отправьте <b>название магазина</b> — это текст его кнопки в списке.\n"
        "Премиум-эмодзи в начале станет иконкой кнопки.",
        "a:shops:0",
    )


@on_input("shopnew", P)
async def in_shop_new(ctx: Ctx, message: Message):
    if not message.text:
        raise InputError("Нужен текст.")
    label, icon = parse_label(message)
    if not label:
        raise InputError("Пустое название.")
    ts = now()
    pos = (await ctx.app.db.fetchval("SELECT COALESCE(MAX(position), -1) + 1 FROM shops")) or 0
    shop_id = await ctx.app.db.execute(
        "INSERT INTO shops(label, icon, html, plain, position, is_active, created_at, updated_at)"
        " VALUES (?, ?, ?, '', ?, 0, ?, ?)",
        (label, icon, f"<b>{escape(label)}</b>", pos, ts, ts),
    )
    await ctx.reload()
    await ctx.log("shop.create", f"{shop_id}: {label}")
    ctx.notice = ("✅ Магазин создан <b>скрытым</b>. Заполните карточку, выберите метки и города, "
                  "затем нажмите «👁 Опубликовать».")
    return f"a:shop:{shop_id}"


@action("shopfind", P)
async def act_shop_find(ctx: Ctx):
    return await ctx.ask("shopfind", "Отправьте часть названия или описания магазина.", "a:shops:0")


@on_input("shopfind", P)
async def in_shop_find(ctx: Ctx, message: Message) -> ViewResult:
    q = (message.text or "").casefold().strip()
    if not q:
        raise InputError("Пустой запрос.")
    found = [s for s in sorted_shops(ctx) if q in s.search_key][:40]
    rows = grid([b(shop_title(s), f"a:shop:{s.id}") for s in found], 2)
    rows.append(back_btn("a:shops:0"))
    return f"🔍 Найдено: {len(found)} по «{escape(q)}»", rows


@view("shop", P)
async def view_shop(ctx: Ctx, shop_id: str) -> ViewResult:
    app = ctx.app
    cat = app.catalog
    shop = cat.shops.get(int(shop_id))
    if shop is None:
        ctx.notice = "Магазин не найден."
        return await view_shops(ctx)
    row = await app.db.fetchone("SELECT * FROM shops WHERE id = ?", (shop.id,))
    tz = int(cat.setting("tz_offset", 5))
    tags = ", ".join(f"{cat.tags[t].label} ({fmt_date(exp, tz)})" for t, exp in shop.tags.items()) or "нет"
    cities = ", ".join(cat.cities[c].label for c in shop.cities if c in cat.cities) or "нет"
    categories = ", ".join(cat.categories[c].label for c in shop.categories if c in cat.categories) or "нет"
    week = await app.db.fetchval(
        "SELECT COUNT(*) FROM events WHERE shop_id = ? AND ts > ?", (shop.id, now() - 7 * 86400))
    month = await app.db.fetchval(
        "SELECT COUNT(*) FROM events WHERE shop_id = ? AND ts > ?", (shop.id, now() - 30 * 86400))
    link = f"https://t.me/{app.bot_username}?start=shop_{shop.id}" if app.bot_username else "—"
    html = (
        f"🏪 <b>{escape(shop.label)}</b>  <code>#{shop.id}</code>\n"
        f"Статус: {'✅ опубликован' if shop.is_active else '🙈 скрыт'}\n"
        f"Проверенный: {'✅ да' if shop.verified else 'нет'}\n"
        f"Иконка кнопки: {icon_line(shop.icon)}\n"
        f"Метки: {escape(tags)}\n"
        f"Города: {escape(cities)}\n"
        f"Категории: {escape(categories)}\n"
        f"Контактов: {len(shop.contacts)}\n"
        f"Медиа: {media_line(app, shop.media_id)}\n"
        f"Просмотры: 7 дн — <b>{week}</b>, 30 дн — <b>{month}</b>\n"
        f"Ссылка: {escape(link)}\n\n"
        f"<b>Текст карточки:</b>\n{snippet(shop.html, 400)}"
    )
    sid = shop.id
    rows: Rows = editor_rows("shop", str(sid), row, app=app)
    rows.append([b("📞 Контакты", f"a:cont:{sid}"), b("👀 Предпросмотр", f"x:sprev:{sid}")])
    rows.append([b("🏷 Метки", f"a:stags:{sid}"), b("🏙 Города", f"a:scity:{sid}:0"),
                 b("🗂 Категории", f"a:scats:{sid}")])
    rows.append([
        b("✅ Проверенный" if not shop.verified else "✖️ Снять «Проверенный»", f"x:sver:{sid}"),
        b("👁 Опубликовать" if not shop.is_active else "🙈 Скрыть", f"x:sact:{sid}",
          "success" if not shop.is_active else None),
    ])
    rows.append([b("⬆️ Выше", f"x:smv:{sid}:-1"), b("⬇️ Ниже", f"x:smv:{sid}:1")])
    rows.append([b("🗑 Удалить", f"a:sdel:{sid}", "danger")])
    rows.append(back_btn("a:shops:0", "◀️ К списку"))
    return html, rows


@action("sprev", P)
async def act_shop_preview(ctx: Ctx, shop_id: str):
    shop = ctx.app.catalog.shops.get(int(shop_id))
    if shop is None:
        return "a:shops:0"
    cat = ctx.app.catalog
    html, media_id, kb = screen_card(ctx.app, cat.tr(cat.base_lang), shop, "m0")
    # кнопки предпросмотра не ведут в каталог — только закрыть
    kb.inline_keyboard[-1] = [button("✖️ Закрыть предпросмотр", cb="x:close")]
    kb.inline_keyboard = [r for r in kb.inline_keyboard if not (r and r[0].callback_data or "").startswith("r:")]
    msg = None
    if media_id:
        msg = await ctx.app.media.send(ctx.app.bot, ctx.chat_id, media_id, html, kb)
    if msg is None:
        await ctx.app.bot.send_message(ctx.chat_id, html, reply_markup=kb)
    await ctx.toast("Предпросмотр отправлен ниже")
    return None


@action("sver", P)
async def act_shop_verified(ctx: Ctx, shop_id: str):
    await ctx.app.db.execute("UPDATE shops SET verified = 1 - verified, updated_at = ? WHERE id = ?", (now(), int(shop_id)))
    await ctx.reload()
    await ctx.log("shop.verified", shop_id)
    return f"a:shop:{shop_id}"


@action("sact", P)
async def act_shop_active(ctx: Ctx, shop_id: str):
    await ctx.app.db.execute("UPDATE shops SET is_active = 1 - is_active, updated_at = ? WHERE id = ?", (now(), int(shop_id)))
    await ctx.reload()
    shop = ctx.app.catalog.shops.get(int(shop_id))
    await ctx.log("shop.publish" if shop and shop.is_active else "shop.hide", shop_id)
    if shop and shop.is_active and not shop.tags and not shop.cities:
        ctx.notice = "⚠️ Магазин опубликован, но без меток и городов — его найдут только через поиск."
    return f"a:shop:{shop_id}"


@action("smv", P)
async def act_shop_move(ctx: Ctx, shop_id: str, delta: str):
    await move(ctx, "shops", int(shop_id), int(delta))
    return f"a:shop:{shop_id}"


@view("sdel", P)
async def view_shop_delete(ctx: Ctx, shop_id: str) -> ViewResult:
    shop = ctx.app.catalog.shops.get(int(shop_id))
    name = escape(shop.label) if shop else shop_id
    return (f"🗑 Удалить магазин <b>{name}</b> навсегда?\nМожно просто скрыть — тогда его легко вернуть.",
            [[b("🗑 Да, удалить", f"x:sdel:{shop_id}", "danger"), b("✖️ Отмена", f"a:shop:{shop_id}")]])


@action("sdel", P)
async def act_shop_delete(ctx: Ctx, shop_id: str):
    shop = ctx.app.catalog.shops.get(int(shop_id))
    await ctx.app.db.execute("DELETE FROM shops WHERE id = ?", (int(shop_id),))
    await ctx.reload()
    await ctx.log("shop.delete", f"{shop_id}: {shop.label if shop else ''}")
    ctx.notice = "🗑 Магазин удалён."
    return "a:shops:0"


# ---------- контакты ----------
CONTACTS_HELP = (
    "Отправьте контакты — каждый с новой строки в формате\n"
    "<code>Текст кнопки | ссылка</code>\n\n"
    "Примеры:\n"
    "<code>💬 Написать | @shop_manager</code>\n"
    "<code>📢 Канал | https://t.me/shop_channel</code>\n"
    "<code>🌐 Сайт | https://example.com</code>\n\n"
    "Премиум-эмодзи в строке станет иконкой кнопки. Список заменится целиком."
)


@view("cont", P)
async def view_contacts(ctx: Ctx, shop_id: str) -> ViewResult:
    shop = ctx.app.catalog.shops.get(int(shop_id))
    if shop is None:
        return await view_shops(ctx)
    lines = "\n".join(f"• {escape(c.label)} → {escape(c.url)}" for c in shop.contacts) or "<i>нет</i>"
    rows: Rows = [[b("✏️ Заменить контакты", f"x:cset:{shop_id}")]]
    if shop.contacts:
        rows.append([b("🗑 Очистить", f"x:cclr:{shop_id}", "danger")])
    rows.append(back_btn(f"a:shop:{shop_id}"))
    return f"📞 <b>Контакты «{escape(shop.label)}»</b>\n\n{lines}", rows


@action("cset", P)
async def act_contacts_set(ctx: Ctx, shop_id: str):
    return await ctx.ask("contacts", CONTACTS_HELP, f"a:cont:{shop_id}", shop_id)


@on_input("contacts", P)
async def in_contacts(ctx: Ctx, message: Message, shop_id: str):
    contacts, errors = parse_contacts(message)
    if errors:
        raise InputError("Не удалось разобрать:\n" + "\n".join(errors[:10]))
    if not contacts:
        raise InputError("Нет ни одного контакта.")
    db = ctx.app.db
    await db.execute("DELETE FROM shop_contacts WHERE shop_id = ?", (int(shop_id),))
    await db.executemany(
        "INSERT INTO shop_contacts(shop_id, label, url, icon, position) VALUES (?, ?, ?, ?, ?)",
        ((int(shop_id), label, url, icon, i) for i, (label, url, icon) in enumerate(contacts)),
    )
    await ctx.reload()
    await ctx.log("shop.contacts", shop_id)
    ctx.notice = "✅ Контакты сохранены"
    return f"a:cont:{shop_id}"


@action("cclr", P)
async def act_contacts_clear(ctx: Ctx, shop_id: str):
    await ctx.app.db.execute("DELETE FROM shop_contacts WHERE shop_id = ?", (int(shop_id),))
    await ctx.reload()
    return f"a:cont:{shop_id}"


# ---------- метки ----------
@view("stags", P)
async def view_shop_tags(ctx: Ctx, shop_id: str) -> ViewResult:
    cat = ctx.app.catalog
    shop = cat.shops.get(int(shop_id))
    if shop is None:
        return await view_shops(ctx)
    tz = int(cat.setting("tz_offset", 5))
    rows: Rows = []
    for tag in cat.tags.values():
        on = tag.id in shop.tags
        r = [b(f"{'✅' if on else '▫️'} {tag.label}", f"x:stt:{shop_id}:{tag.id}")]
        if on:
            r.append(b(f"⏳ {fmt_date(shop.tags[tag.id], tz)}", f"x:stexp:{shop_id}:{tag.id}"))
        rows.append(r)
    rows.append(back_btn(f"a:shop:{shop_id}"))
    html = (f"🏷 <b>Метки «{escape(shop.label)}»</b>\n\n"
            "Нажмите на метку, чтобы включить/выключить. ⏳ — срок размещения: "
            "по его окончании метка снимется сама, а за сутки придёт напоминание.")
    return html, rows


@action("stt", P)
async def act_shop_tag_toggle(ctx: Ctx, shop_id: str, tag_id: str):
    db = ctx.app.db
    exists = await db.fetchval("SELECT 1 FROM shop_tags WHERE shop_id = ? AND tag_id = ?", (int(shop_id), int(tag_id)))
    if exists:
        await db.execute("DELETE FROM shop_tags WHERE shop_id = ? AND tag_id = ?", (int(shop_id), int(tag_id)))
    else:
        await db.execute("INSERT INTO shop_tags(shop_id, tag_id) VALUES (?, ?)", (int(shop_id), int(tag_id)))
    await ctx.reload()
    await ctx.log("shop.tag_off" if exists else "shop.tag_on", f"{shop_id}/{tag_id}")
    return f"a:stags:{shop_id}"


@action("stexp", P)
async def act_shop_tag_expiry(ctx: Ctx, shop_id: str, tag_id: str):
    return await ctx.ask(
        "tagexp",
        "Отправьте срок размещения:\n"
        "• число дней, например <code>30</code>\n"
        "• или дату окончания <code>ДД.ММ.ГГГГ</code>\n"
        "• <code>0</code> — бессрочно",
        f"a:stags:{shop_id}", shop_id, tag_id,
    )


def parse_expiry(text: str, tz: int) -> int | None:
    text = text.strip()
    if text.isdigit():
        days = int(text)
        return None if days == 0 else now() + days * 86400
    try:
        d = datetime.strptime(text, "%d.%m.%Y").replace(hour=23, minute=59, tzinfo=timezone(timedelta(hours=tz)))
    except ValueError:
        raise InputError("Не понял срок. Пример: 30 или 31.12.2026")
    if d.timestamp() <= time.time():
        raise InputError("Дата уже прошла.")
    return int(d.timestamp())


@on_input("tagexp", P)
async def in_tag_expiry(ctx: Ctx, message: Message, shop_id: str, tag_id: str):
    until = parse_expiry(message.text or "", int(ctx.app.catalog.setting("tz_offset", 5)))
    await ctx.app.db.execute(
        "UPDATE shop_tags SET expires_at = ?, notified = 0 WHERE shop_id = ? AND tag_id = ?",
        (until, int(shop_id), int(tag_id)),
    )
    await ctx.reload()
    await ctx.log("shop.tag_expiry", f"{shop_id}/{tag_id}: {until}")
    ctx.notice = "✅ Срок сохранён"
    return f"a:stags:{shop_id}"


# ---------- города ----------
@view("scity", P)
async def view_shop_cities(ctx: Ctx, shop_id: str, page: str = "0") -> ViewResult:
    cat = ctx.app.catalog
    shop = cat.shops.get(int(shop_id))
    if shop is None:
        return await view_shops(ctx)
    cities = sorted(cat.cities.values(), key=lambda c: (not c.is_main, c.position, c.label))
    chunk, p, pages = paginate(cities, int(page), 30)
    rows = grid([b(f"{'✅' if c.id in shop.cities else '▫️'} {c.label}", f"x:sct:{shop_id}:{c.id}:{p}")
                 for c in chunk], 2)
    nav = []
    if p > 0:
        nav.append(b("◀️", f"a:scity:{shop_id}:{p - 1}"))
    if pages > 1:
        nav.append(button(f"{p + 1}/{pages}", cb="noop"))
    if p < pages - 1:
        nav.append(b("▶️", f"a:scity:{shop_id}:{p + 1}"))
    rows.append(nav)
    rows.append([b("✅ Все", f"x:scall:{shop_id}:1"), b("▫️ Ни одного", f"x:scall:{shop_id}:0")])
    rows.append(back_btn(f"a:shop:{shop_id}"))
    return f"🏙 <b>Города «{escape(shop.label)}»</b> — выбрано {len(shop.cities)}", rows


@action("sct", P)
async def act_shop_city_toggle(ctx: Ctx, shop_id: str, city_id: str, page: str):
    db = ctx.app.db
    args = (int(shop_id), int(city_id))
    if await db.fetchval("SELECT 1 FROM shop_cities WHERE shop_id = ? AND city_id = ?", args):
        await db.execute("DELETE FROM shop_cities WHERE shop_id = ? AND city_id = ?", args)
    else:
        await db.execute("INSERT INTO shop_cities(shop_id, city_id) VALUES (?, ?)", args)
    await ctx.reload()
    return f"a:scity:{shop_id}:{page}"


@action("scall", P)
async def act_shop_city_all(ctx: Ctx, shop_id: str, on: str):
    db = ctx.app.db
    await db.execute("DELETE FROM shop_cities WHERE shop_id = ?", (int(shop_id),))
    if on == "1":
        await db.executemany("INSERT INTO shop_cities(shop_id, city_id) VALUES (?, ?)",
                             ((int(shop_id), c) for c in ctx.app.catalog.cities))
    await ctx.reload()
    return f"a:scity:{shop_id}:0"


# ---------- категории магазина ----------
@view("scats", P)
async def view_shop_categories(ctx: Ctx, shop_id: str) -> ViewResult:
    cat = ctx.app.catalog
    shop = cat.shops.get(int(shop_id))
    if shop is None:
        return await view_shops(ctx)
    rows = grid([b(f"{'✅' if c.id in shop.categories else '▫️'} {c.label}", f"x:scat:{shop_id}:{c.id}")
                 for c in cat.categories.values()], 2)
    rows.append(back_btn(f"a:shop:{shop_id}"))
    return (f"🗂 <b>Категории «{escape(shop.label)}»</b>\nОтметьте, что продаёт магазин. "
            "Ассортимент поменялся — просто переставьте галочки."), rows


@action("scat", P)
async def act_shop_category_toggle(ctx: Ctx, shop_id: str, cat_id: str):
    db = ctx.app.db
    args = (int(shop_id), int(cat_id))
    if await db.fetchval("SELECT 1 FROM shop_categories WHERE shop_id = ? AND category_id = ?", args):
        await db.execute("DELETE FROM shop_categories WHERE shop_id = ? AND category_id = ?", args)
    else:
        await db.execute("INSERT INTO shop_categories(shop_id, category_id) VALUES (?, ?)", args)
    await ctx.reload()
    await ctx.log("shop.categories", shop_id)
    return f"a:scats:{shop_id}"
