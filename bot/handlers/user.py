"""Пользовательская часть. Все тексты/кнопки берутся из кэша каталога на языке пользователя.

Callback-данные (≤64 байт):
  m:<item>                      пункт меню
  l:<item>:<page>               список магазинов пункта (метка / все / избранное)
  o:<item>:<page>               другие города
  y:<city>:<item>:<page>        город: категории (или сразу магазины, если категорий нет)
  k:<city>:<cat>:<item>:<page>  магазины города в категории (cat=0 — все магазины города)
  g:<cat>:<item>:<page>         магазины категории во всех городах
  s:<shop>:<ctx>                карточка; ctx — куда вести «Назад» (m1, l5.0, y3.4.0, k3.2.4.0, g2.4.0, q0)
  f:<shop>:<ctx>                добавить/убрать из избранного
  q:<page>                      результаты поиска
  r:<shop>:<ctx>                жалоба
  L:<lang>                      выбор языка
  ap:<go|skip|send|cancel>      заявка на размещение
"""
import json
import re
from html import escape
from urllib.parse import quote

from aiogram import F, Router
from aiogram.filters import CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, Message

from .. import search
from ..app import App
from ..catalog import AppField, MenuItem, Shop, Tr, now
from ..media import MediaError
from ..richtext import CAPTION_LIMIT, html_to_plain, message_html
from ..ui import button, current_of, fill, grid, markup, nav_row, paginate, safe_delete, show, sys_button

router = Router(name="user")


class Search(StatesGroup):
    query = State()


class Report(StatesGroup):
    text = State()


class Apply(StatesGroup):
    answer = State()


def ctx_to_cb(ctx: str) -> str:
    return f"{ctx[0]}:{ctx[1:].replace('.', ':')}" if ctx else "m:0"


def plain(html: str) -> str:
    return html_to_plain(html)[:190]


# ---------- сборка экранов ----------
def item_button(tr: Tr, item: MenuItem) -> InlineKeyboardButton:
    label = tr.label("item", item)
    if item.kind == "url":
        return button(label, item.icon, item.style, url=item.payload or "https://t.me")
    return button(label, item.icon, item.style, cb=f"m:{item.id}")


def back_to_parent(tr: Tr, item: MenuItem) -> list[InlineKeyboardButton]:
    if item.parent_id is None:
        return []
    return [sys_button(tr, "back", f"m:{item.parent_id}")]


def city_rows(app: App, tr: Tr, block: MenuItem, user_id: int) -> list[list[InlineKeyboardButton]]:
    """Блок городов: «📍 Мой город» (если он не среди главных), главные города по 2 в ряд, «Другие города»."""
    cat = app.catalog
    rows: list[list[InlineKeyboardButton]] = []
    mine = cat.cities.get(app.last_city.get(user_id, 0))
    if mine and mine.is_active and not mine.is_main:
        b = tr.button("my_city")
        rows.append([button(fill(b.label, city=tr.label("city", mine)), b.icon or mine.icon, b.style or mine.style,
                            cb=f"y:{mine.id}:{block.id}:0")])
    btns = [button(tr.label("city", c), c.icon, c.style, cb=f"y:{c.id}:{block.id}:0") for c in cat.main_cities]
    if cat.other_cities:
        btns.append(sys_button(tr, "other_cities", f"o:{block.id}:0"))
    return rows + grid(btns, int(cat.setting("per_row", 2)))


def screen_menu(app: App, tr: Tr, item: MenuItem, first_name: str, user_id: int = 0):
    cat = app.catalog
    rows: dict[int, list[InlineKeyboardButton]] = {}
    blocks: dict[int, list[list[InlineKeyboardButton]]] = {}
    for child in cat.active_children(item.id):
        if child.kind == "language" and len(cat.languages) < 2:
            continue
        if child.kind == "city_block":
            blocks.setdefault(child.row, []).extend(city_rows(app, tr, child, user_id))
        else:
            rows.setdefault(child.row, []).append(item_button(tr, child))
    kb: list[list[InlineKeyboardButton]] = []
    for r in sorted(set(rows) | set(blocks)):
        if r in rows:
            kb.append(rows[r])
        kb.extend(blocks.get(r, []))
    kb.append(back_to_parent(tr, item))
    return fill(tr.html("item", item), first_name=first_name), item.media_id, markup(kb)


def shop_buttons(tr: Tr, shops: list[Shop], ctx: str) -> list[InlineKeyboardButton]:
    return [button(tr.label("shop", s), s.icon, s.style, cb=f"s:{s.id}:{ctx}") for s in shops]


def shop_list(app: App, tr: Tr, shops: list[Shop], page: int, header: str, ctx_prefix: str,
              page_cb: str, back_cb: str | None, empty_key: str = "empty"):
    """Общий список магазинов: сетка, страницы, «Назад». ctx_prefix/page_cb — без номера страницы."""
    cat = app.catalog
    chunk, page, pages = paginate(shops, page, int(cat.setting("page_size", 10)))
    if not shops:
        header += "\n\n" + tr.text(empty_key)
    kb = grid(shop_buttons(tr, list(chunk), f"{ctx_prefix}{page}"), int(cat.setting("per_row", 2)))
    kb.append(nav_row(tr, page, pages, lambda p: f"{page_cb}{p}"))
    if back_cb:
        kb.append([sys_button(tr, "back", back_cb)])
    return header, kb


def screen_item_list(app: App, tr: Tr, item: MenuItem, page: int, favorites: list[int] | None = None):
    cat = app.catalog
    empty = "empty"
    if item.kind == "all":
        shops = cat.all_shops
    elif item.kind == "favorites":
        shops = [cat.shops[i] for i in favorites or [] if i in cat.shops and cat.shops[i].is_active]
        empty = "favorites_empty"
    else:
        shops = cat.by_tag.get(int(item.payload or 0), [])
    header = tr.html("item", item) or (tr.text("favorites") if item.kind == "favorites" else tr.label("item", item))
    back = f"m:{item.parent_id}" if item.parent_id else None
    html, kb = shop_list(app, tr, shops, page, header, f"l{item.id}.", f"l:{item.id}:", back, empty)
    return html, item.media_id, markup(kb)


def screen_cities(app: App, tr: Tr, item: MenuItem, user_id: int = 0):
    cat = app.catalog
    kb = city_rows(app, tr, item, user_id)
    kb.append(back_to_parent(tr, item))
    return tr.html("item", item) or tr.text("cities"), item.media_id or cat.text("cities").media_id, markup(kb)


def screen_other_cities(app: App, tr: Tr, item_id: int, page: int):
    cat = app.catalog
    if cat.setting("other_cities_as_shops", 1):
        # сразу магазины из всех не главных городов, город написан в карточке
        html, kb = shop_list(app, tr, cat.other_shops, page, tr.text("other_cities"), f"o{item_id}.",
                             f"o:{item_id}:", f"m:{item_id}")
        return html, cat.text("other_cities").media_id, markup(kb)
    chunk, page, pages = paginate(cat.other_cities, page, int(cat.setting("page_size", 10)))
    btns = [button(tr.label("city", c), c.icon, c.style, cb=f"y:{c.id}:{item_id}:0") for c in chunk]
    kb = grid(btns, int(cat.setting("per_row", 2)))
    kb.append(nav_row(tr, page, pages, lambda p: f"o:{item_id}:{p}"))
    kb.append([sys_button(tr, "back", f"m:{item_id}")])
    return tr.text("other_cities"), cat.text("other_cities").media_id, markup(kb)


def city_back(app: App, city_id: int, item_id: int) -> str:
    """Назад из города — к главным городам или на нужную страницу «Других городов»."""
    cat = app.catalog
    city = cat.cities[city_id]
    if city.is_main or city not in cat.other_cities:
        return f"m:{item_id}"
    size = max(1, int(cat.setting("page_size", 10)))
    return f"o:{item_id}:{cat.other_cities.index(city) // size}"


def screen_city(app: App, tr: Tr, city_id: int, item_id: int, page: int):
    cat = app.catalog
    city = cat.cities.get(city_id)
    if city is None:
        return None
    city_name = tr.label("city", city)
    cats = cat.city_categories.get(city_id, []) if cat.setting("city_categories", 1) else []
    if len(cat.by_city.get(city_id, [])) <= int(cat.setting("city_categories_min", 6)):
        cats = []  # магазинов мало — категории только мешают
    if not cats:  # категорий нет — сразу магазины
        header = fill(tr.text("city_shops"), city=city_name)
        html, kb = shop_list(app, tr, cat.by_city.get(city_id, []), page, header, f"y{city_id}.{item_id}.",
                             f"y:{city_id}:{item_id}:", city_back(app, city_id, item_id))
        return html, cat.text("city_shops").media_id, markup(kb)
    chunk, page, pages = paginate(cats, page, int(cat.setting("page_size", 10)))
    btns = [button(tr.label("cat", c), c.icon, c.style, cb=f"k:{city_id}:{c.id}:{item_id}:0") for c in chunk]
    btns.append(sys_button(tr, "all_shops", f"k:{city_id}:0:{item_id}:0"))
    kb = grid(btns, int(cat.setting("per_row", 2)))
    kb.append(nav_row(tr, page, pages, lambda p: f"y:{city_id}:{item_id}:{p}"))
    kb.append([sys_button(tr, "back", city_back(app, city_id, item_id))])
    return fill(tr.text("city_categories"), city=city_name), cat.text("city_categories").media_id, markup(kb)


def screen_city_category(app: App, tr: Tr, city_id: int, cat_id: int, item_id: int, page: int):
    cat = app.catalog
    city = cat.cities.get(city_id)
    category = cat.categories.get(cat_id)
    if city is None or (cat_id and category is None):
        return None
    if cat_id:
        shops = cat.by_city_category.get((city_id, cat_id), [])
        header = fill(tr.text("city_category_shops"), city=tr.label("city", city), category=tr.label("cat", category))
    else:
        shops = cat.by_city.get(city_id, [])
        header = fill(tr.text("city_shops"), city=tr.label("city", city))
    html, kb = shop_list(app, tr, shops, page, header, f"k{city_id}.{cat_id}.{item_id}.",
                         f"k:{city_id}:{cat_id}:{item_id}:", f"y:{city_id}:{item_id}:0")
    return html, None, markup(kb)


def screen_categories(app: App, tr: Tr, item: MenuItem):
    cat = app.catalog
    cats = [c for c in cat.active_categories if cat.by_category.get(c.id)]
    btns = [button(tr.label("cat", c), c.icon, c.style, cb=f"g:{c.id}:{item.id}:0") for c in cats]
    kb = grid(btns, int(cat.setting("per_row", 2)))
    kb.append(back_to_parent(tr, item))
    html = tr.html("item", item) or tr.text("categories")
    if not cats:
        html += "\n\n" + tr.text("empty")
    return html, item.media_id, markup(kb)


def screen_category(app: App, tr: Tr, cat_id: int, item_id: int, page: int):
    cat = app.catalog
    category = cat.categories.get(cat_id)
    if category is None:
        return None
    header = fill(tr.text("category_shops"), category=tr.label("cat", category))
    html, kb = shop_list(app, tr, cat.by_category.get(cat_id, []), page, header, f"g{cat_id}.{item_id}.",
                         f"g:{cat_id}:{item_id}:", f"m:{item_id}")
    return html, None, markup(kb)


_PERSON_LINK = re.compile(r"^https://t\.me/([A-Za-z0-9_]{4,32})/?$")


def contact_url(url: str, greeting: str) -> str:
    """Ссылка на @username открывает чат с уже вписанным приветствием (человек сам жмёт «Отправить»)."""
    if greeting and _PERSON_LINK.match(url):
        return f"{url.rstrip('/')}?text={quote(greeting)}"
    return url


def cities_line(app: App, tr: Tr, shop: Shop) -> str:
    """«🏙 Города: Алматы, Астана» — строится сам из отмеченных у магазина городов."""
    cat = app.catalog
    active = [c for c in cat.cities.values() if c.is_active]
    mine = [c for c in active if c.id in shop.cities]
    if not mine or not cat.setting("card_show_cities", 1):
        return ""
    if len(mine) == len(active) and len(active) > 1:
        return tr.text("card_cities_all")
    mine.sort(key=lambda c: (not c.is_main, c.position, c.label))
    return fill(tr.text("card_cities"), cities=", ".join(tr.label("city", c) for c in mine))


def screen_card(app: App, tr: Tr, shop: Shop, ctx: str, is_fav: bool = False):
    html = tr.html("shop", shop) or tr.label("shop", shop)
    if shop.verified:
        html = tr.text("verified_badge") + "\n\n" + html
    line = cities_line(app, tr, shop)
    # с картинкой Telegram пропускает не больше 1024 символов подписи — строку городов тогда не добавляем
    if line and (not shop.media_id or len(html_to_plain(html + line)) < CAPTION_LIMIT - 2):
        html += "\n\n" + line
    greeting = html_to_plain(tr.text("contact_greeting")).strip()
    kb = [[button(c.label, c.icon, c.style, url=contact_url(c.url, greeting))] for c in shop.contacts]
    row = [sys_button(tr, "fav_remove" if is_fav else "fav_add", f"f:{shop.id}:{ctx}")]
    if app.bot_username:  # делятся ссылкой на магазин в боте, а не пересылкой сообщения
        link = f"https://t.me/{app.bot_username}?start=shop_{shop.id}"
        share = tr.button("share")
        row.append(button(share.label, share.icon, share.style,
                          url=f"https://t.me/share/url?url={quote(link)}&text={quote(tr.label('shop', shop))}"))
    kb.append(row)
    kb.append([sys_button(tr, "report", f"r:{shop.id}:{ctx}")])
    kb.append([sys_button(tr, "back", ctx_to_cb(ctx))])
    return html, shop.media_id, markup(kb)


def screen_search_results(app: App, tr: Tr, query: str, page: int):
    cat = app.catalog
    results, parsed = search.run(cat, query)
    search_item = next((i for i in cat.menu.values() if i.kind == "search" and i.is_active), None)
    back = f"m:{search_item.parent_id}" if search_item and search_item.parent_id else f"m:{cat.root_id}"
    header = fill(tr.text("search_results" if results else "search_empty"), query=query)
    filters = search.describe(cat, tr, parsed)
    if filters:
        header += f"\n<i>{escape(filters)}</i>"
    html, kb = shop_list(app, tr, results, page, header, "q", "q:", back)
    if not results:  # «Ничего не найдено» уже сказано — без «пусто»
        html = header
    return html, None, markup(kb)


def screen_language(app: App, tr: Tr, item: MenuItem, lang: str):
    rows = [[button(("✅ " if code == lang else "") + name, cb=f"L:{code}")]
            for code, name in app.catalog.languages.items()]
    rows.append(back_to_parent(tr, item))
    return tr.html("item", item) or tr.text("language"), item.media_id, markup(rows)


async def open_card(app: App, tr: Tr, uid: int, chat_id: int, shop: Shop, ctx: str, current=None) -> None:
    app.track(shop.id, uid)
    is_fav = await app.is_favorite(uid, shop.id)
    await show(app, uid, chat_id, *screen_card(app, tr, shop, ctx, is_fav), current=current)


def root_screen(app: App, tr: Tr, first_name: str, user_id: int = 0):
    return screen_menu(app, tr, app.catalog.menu[app.catalog.root_id], first_name, user_id)


# ---------- /start ----------
@router.message(CommandStart())
async def cmd_start(message: Message, command: CommandObject, state: FSMContext, app: App, tr: Tr) -> None:
    await state.clear()
    user = message.from_user
    await safe_delete(app, message.chat.id, message.message_id)
    arg = command.args or ""
    if arg.startswith("shop_") and arg[5:].isdigit():
        shop = app.catalog.shops.get(int(arg[5:]))
        if shop and shop.is_active:
            await open_card(app, tr, user.id, message.chat.id, shop, f"m{app.catalog.root_id}")
            return
    if app.catalog.menu.get(app.catalog.root_id) is None:
        await message.answer("Бот ещё не настроен.")
        return
    await show(app, user.id, message.chat.id, *root_screen(app, tr, user.first_name or "", user.id))


# ---------- навигация ----------
@router.callback_query(F.data.startswith("m:"))
async def cb_menu(call: CallbackQuery, state: FSMContext, app: App, tr: Tr, lang: str) -> None:
    cat = app.catalog
    item = cat.menu.get(int(call.data[2:]) or cat.root_id)
    if item is None or not item.is_active:
        item = cat.menu[cat.root_id]
    if item.kind == "city_block":  # «Назад» из города, открытого с блока, ведёт в меню, где этот блок
        item = cat.menu.get(item.parent_id) or cat.menu[cat.root_id]
    await state.set_state(None)
    cur = current_of(call.message)
    uid, chat_id = call.from_user.id, call.message.chat.id
    if item.kind in ("tag", "all", "favorites"):
        favs = await app.favorite_ids(uid) if item.kind == "favorites" else None
        await show(app, uid, chat_id, *screen_item_list(app, tr, item, 0, favs), current=cur)
    elif item.kind == "cities":
        await show(app, uid, chat_id, *screen_cities(app, tr, item, uid), current=cur)
    elif item.kind == "categories":
        await show(app, uid, chat_id, *screen_categories(app, tr, item), current=cur)
    elif item.kind == "language":
        await show(app, uid, chat_id, *screen_language(app, tr, item, lang), current=cur)
    elif item.kind == "apply":
        await apply_intro(call, app, tr, item)
    elif item.kind == "search":
        await state.set_state(Search.query)
        kb = markup([back_to_parent(tr, item)])
        await show(app, uid, chat_id, tr.html("item", item) or tr.text("search_prompt"),
                   item.media_id or cat.text("search_prompt").media_id, kb, current=cur)
    else:
        await show(app, uid, chat_id, *screen_menu(app, tr, item, call.from_user.first_name or "", uid), current=cur)
    await call.answer()


@router.callback_query(F.data.startswith("l:"))
async def cb_list(call: CallbackQuery, state: FSMContext, app: App, tr: Tr) -> None:
    _, item_id, page = call.data.split(":")
    item = app.catalog.menu.get(int(item_id))
    if item is None or item.kind not in ("tag", "all", "favorites"):
        return await cb_home(call, state, app, tr)
    await state.set_state(None)
    favs = await app.favorite_ids(call.from_user.id) if item.kind == "favorites" else None
    await show(app, call.from_user.id, call.message.chat.id, *screen_item_list(app, tr, item, int(page), favs),
               current=current_of(call.message))
    await call.answer()


@router.callback_query(F.data.startswith("o:"))
async def cb_other_cities(call: CallbackQuery, state: FSMContext, app: App, tr: Tr) -> None:
    _, item_id, page = call.data.split(":")
    await state.set_state(None)
    await show(app, call.from_user.id, call.message.chat.id, *screen_other_cities(app, tr, int(item_id), int(page)),
               current=current_of(call.message))
    await call.answer()


async def _show_or_home(call: CallbackQuery, state: FSMContext, app: App, tr: Tr, screen) -> None:
    if screen is None:
        return await cb_home(call, state, app, tr)
    await state.set_state(None)
    await show(app, call.from_user.id, call.message.chat.id, *screen, current=current_of(call.message))
    await call.answer()


@router.callback_query(F.data.startswith("y:"))
async def cb_city(call: CallbackQuery, state: FSMContext, app: App, tr: Tr) -> None:
    _, city_id, item_id, page = call.data.split(":")
    if int(city_id) in app.catalog.cities:
        await app.remember_city(call.from_user.id, int(city_id))
    await _show_or_home(call, state, app, tr, screen_city(app, tr, int(city_id), int(item_id), int(page)))


@router.callback_query(F.data.startswith("k:"))
async def cb_city_category(call: CallbackQuery, state: FSMContext, app: App, tr: Tr) -> None:
    _, city_id, cat_id, item_id, page = call.data.split(":")
    await _show_or_home(call, state, app, tr,
                        screen_city_category(app, tr, int(city_id), int(cat_id), int(item_id), int(page)))


@router.callback_query(F.data.startswith("g:"))
async def cb_category(call: CallbackQuery, state: FSMContext, app: App, tr: Tr) -> None:
    _, cat_id, item_id, page = call.data.split(":")
    await _show_or_home(call, state, app, tr, screen_category(app, tr, int(cat_id), int(item_id), int(page)))


@router.callback_query(F.data.startswith("s:"))
async def cb_shop(call: CallbackQuery, state: FSMContext, app: App, tr: Tr) -> None:
    _, shop_id, ctx = call.data.split(":", 2)
    shop = app.catalog.shops.get(int(shop_id))
    if shop is None or not shop.is_active:
        await call.answer(plain(tr.text("shop_unavailable")), show_alert=True)
        return
    await state.set_state(None)
    await open_card(app, tr, call.from_user.id, call.message.chat.id, shop, ctx, current_of(call.message))
    await call.answer()


@router.callback_query(F.data.startswith("f:"))
async def cb_favorite(call: CallbackQuery, app: App, tr: Tr) -> None:
    _, shop_id, ctx = call.data.split(":", 2)
    shop = app.catalog.shops.get(int(shop_id))
    if shop is None:
        await call.answer()
        return
    added = await app.toggle_favorite(call.from_user.id, shop.id)
    await show(app, call.from_user.id, call.message.chat.id, *screen_card(app, tr, shop, ctx, added),
               current=current_of(call.message))
    await call.answer(plain(tr.text("fav_added" if added else "fav_removed")))


@router.callback_query(F.data.startswith("q:"))
async def cb_search_page(call: CallbackQuery, state: FSMContext, app: App, tr: Tr) -> None:
    query = (await state.get_data()).get("query")
    if not query:
        return await cb_home(call, state, app, tr)
    await state.set_state(Search.query)
    await show(app, call.from_user.id, call.message.chat.id,
               *screen_search_results(app, tr, query, int(call.data[2:])), current=current_of(call.message))
    await call.answer()


@router.callback_query(F.data.startswith("L:"))
async def cb_language(call: CallbackQuery, state: FSMContext, app: App) -> None:
    lang = call.data[2:]
    if lang in app.catalog.languages:
        await app.set_lang(call.from_user.id, lang)
    await cb_home(call, state, app, app.catalog.tr(app.user_lang(call.from_user.id, call.from_user.language_code)))


@router.callback_query(F.data == "noop")
async def cb_noop(call: CallbackQuery) -> None:
    await call.answer()


async def cb_home(call: CallbackQuery, state: FSMContext, app: App, tr: Tr) -> None:
    await state.set_state(None)
    await show(app, call.from_user.id, call.message.chat.id,
               *root_screen(app, tr, call.from_user.first_name or "", call.from_user.id), current=current_of(call.message))
    await call.answer()


# ---------- поиск ----------
@router.message(Search.query, F.text)
async def on_search(message: Message, state: FSMContext, app: App, tr: Tr) -> None:
    await safe_delete(app, message.chat.id, message.message_id)
    query = " ".join(message.text.split())[:64]
    await state.update_data(query=query)
    await show(app, message.from_user.id, message.chat.id, *screen_search_results(app, tr, query, 0),
               current=app.screens.get(message.from_user.id))


# ---------- жалобы ----------
@router.callback_query(F.data.startswith("r:"))
async def cb_report(call: CallbackQuery, state: FSMContext, app: App, tr: Tr) -> None:
    _, shop_id, ctx = call.data.split(":", 2)
    shop = app.catalog.shops.get(int(shop_id))
    if shop is None:
        return await cb_home(call, state, app, tr)
    cooldown = int(app.catalog.setting("report_cooldown_minutes", 60)) * 60
    last = await app.db.fetchval("SELECT MAX(created_at) FROM reports WHERE user_id = ?", (call.from_user.id,))
    if last and now() - last < cooldown:
        await call.answer(plain(tr.text("report_limit")), show_alert=True)
        return
    await state.set_state(Report.text)
    await state.update_data(report_shop=shop.id, report_ctx=ctx)
    kb = markup([[sys_button(tr, "back", f"s:{shop.id}:{ctx}")]])
    await show(app, call.from_user.id, call.message.chat.id,
               fill(tr.text("report_prompt"), shop=tr.label("shop", shop)), None, kb,
               current=current_of(call.message))
    await call.answer()


@router.message(Report.text, F.text)
async def on_report(message: Message, state: FSMContext, app: App, tr: Tr) -> None:
    await safe_delete(app, message.chat.id, message.message_id)
    data = await state.get_data()
    await state.set_state(None)
    shop = app.catalog.shops.get(data.get("report_shop", 0))
    if shop is None:
        return
    report_id = await app.db.execute(
        "INSERT INTO reports(shop_id, user_id, text, created_at) VALUES (?, ?, ?, ?)",
        (shop.id, message.from_user.id, message.text[:1000], now()),
    )
    kb = markup([[sys_button(tr, "back", f"s:{shop.id}:{data.get('report_ctx', 'm0')}")]])
    await show(app, message.from_user.id, message.chat.id, tr.text("report_thanks"), None, kb,
               current=app.screens.get(message.from_user.id))
    html = (f"🚩 <b>Жалоба #{report_id}</b> на магазин <b>{escape(shop.label)}</b>\n"
            f"От: <code>{message.from_user.id}</code>\n\n{escape(message.text[:1000])}")
    await app.notify_admins(html, perm="reports", reply_markup=markup([[button("Открыть", cb=f"a:rep:{report_id}")]]))
    await app.log_event(html)


# ---------- заявка на размещение ----------
def _cancel_row(tr: Tr) -> list[InlineKeyboardButton]:
    return [sys_button(tr, "apply_cancel", "ap:cancel")]


async def apply_intro(call: CallbackQuery, app: App, tr: Tr, item: MenuItem) -> None:
    uid = call.from_user.id
    pending = await app.db.fetchval("SELECT 1 FROM applications WHERE user_id = ? AND status = 'new'", (uid,))
    kb = [back_to_parent(tr, item)]
    if pending:
        html = tr.text("apply_pending")
    else:
        html = tr.html("item", item) or tr.text("apply_intro")
        cooldown = int(app.catalog.setting("apply_cooldown_hours", 24)) * 3600
        last = await app.db.fetchval("SELECT MAX(created_at) FROM applications WHERE user_id = ?", (uid,))
        if last and now() - last < cooldown:
            html += "\n\n" + tr.text("apply_cooldown")
        elif app.catalog.fields:
            kb.insert(0, [sys_button(tr, "apply_start", "ap:go")])
    await show(app, uid, call.message.chat.id, html, item.media_id, markup(kb), current=current_of(call.message))


def field_prompt(tr: Tr, fields: list[AppField], idx: int, error: str = ""):
    f = fields[idx]
    html = fill(tr.text("apply_step"), step=idx + 1, total=len(fields)) + "\n\n" + tr.get("field", f.id, "html", f.html)
    if error:
        html = f"{error}\n\n{html}"
    kb = []
    if not f.required:
        kb.append([sys_button(tr, "apply_skip", "ap:skip")])
    kb.append(_cancel_row(tr))
    return html, None, markup(kb)


def apply_summary(tr: Tr, answers: list[dict]):
    parts = [tr.text("apply_confirm")]
    for a in answers:
        value = a["html"] or ("📎" if a["media_id"] else "<i>пропущено</i>")
        if a["html"] and a["media_id"]:
            value = "📎 " + value
        parts.append(f"<b>{escape(tr.get('field', a['field_id'], 'label', a['label']))}</b>\n{value}")
    html = "\n\n".join(parts)
    if len(html) > 3900:
        html = html[:3900] + "…"
    kb = [[sys_button(tr, "apply_send", "ap:send")], [sys_button(tr, "apply_restart", "ap:go")], _cancel_row(tr)]
    return html, None, markup(kb)


async def _apply_next(app: App, tr: Tr, uid: int, chat_id: int, state: FSMContext, current) -> None:
    data = await state.get_data()
    fields = app.catalog.fields
    idx = data.get("apply_idx", 0)
    if idx >= len(fields):
        await state.set_state(None)
        await show(app, uid, chat_id, *apply_summary(tr, data.get("apply_answers", [])), current=current)
    else:
        await state.set_state(Apply.answer)
        await show(app, uid, chat_id, *field_prompt(tr, fields, idx), current=current)


@router.callback_query(F.data.startswith("ap:"))
async def cb_apply(call: CallbackQuery, state: FSMContext, app: App, tr: Tr) -> None:
    step = call.data[3:]
    uid, chat_id, cur = call.from_user.id, call.message.chat.id, current_of(call.message)
    if step == "cancel":
        await state.update_data(apply_answers=[], apply_idx=0)
        return await cb_home(call, state, app, tr)
    if step == "go":
        if await app.db.fetchval("SELECT 1 FROM applications WHERE user_id = ? AND status = 'new'", (uid,)):
            await call.answer(plain(tr.text("apply_pending")), show_alert=True)
            return
        await state.update_data(apply_answers=[], apply_idx=0)
    elif step == "skip":
        data = await state.get_data()
        idx = data.get("apply_idx", 0)
        fields = app.catalog.fields
        if idx < len(fields) and not fields[idx].required:
            await state.update_data(apply_idx=idx + 1)
    elif step == "send":
        data = await state.get_data()
        answers = data.get("apply_answers") or []
        if not answers:
            return await cb_home(call, state, app, tr)
        await submit_application(app, call.from_user, answers)
        await state.update_data(apply_answers=[], apply_idx=0)
        await state.set_state(None)
        kb = markup([[sys_button(tr, "back", f"m:{app.catalog.root_id}")]])
        await show(app, uid, chat_id, tr.text("apply_done"), None, kb, current=cur)
        await call.answer()
        return
    await _apply_next(app, tr, uid, chat_id, state, cur)
    await call.answer()


@router.message(Apply.answer, ~F.text.startswith("/"))
async def on_apply_answer(message: Message, state: FSMContext, app: App, tr: Tr) -> None:
    uid = message.from_user.id
    await safe_delete(app, message.chat.id, message.message_id)
    data = await state.get_data()
    fields = app.catalog.fields
    idx = data.get("apply_idx", 0)
    if idx >= len(fields):
        return
    f = fields[idx]
    has_media = bool(message.photo or message.animation or message.video or message.document)
    ok = {"text": bool(message.text), "media": has_media, "any": bool(message.text) or has_media}.get(f.kind, False)
    error = "" if ok else tr.text("apply_wrong")
    media_id = None
    if ok and has_media:
        try:
            max_mb = float(app.catalog.setting("max_media_mb", 10))
            media_id = await app.media.save_from_message(app.bot, message, int(max_mb * 1048576))
        except MediaError as e:
            error = f"⚠️ {escape(str(e))}"
    if error:
        await show(app, uid, message.chat.id, *field_prompt(tr, fields, idx, error), current=app.screens.get(uid))
        return
    html, text = message_html(message)
    answers = data.get("apply_answers", []) + [{
        "field_id": f.id, "label": f.label, "role": f.role, "html": html[:3000], "plain": text[:3000],
        "media_id": media_id,
    }]
    await state.update_data(apply_answers=answers, apply_idx=idx + 1)
    await _apply_next(app, tr, uid, message.chat.id, state, app.screens.get(uid))


async def submit_application(app: App, user, answers: list[dict]) -> int:
    app_id = await app.db.execute(
        "INSERT INTO applications(user_id, answers, created_at) VALUES (?, ?, ?)",
        (user.id, json.dumps(answers, ensure_ascii=False), now()),
    )
    name = next((a["plain"] for a in answers if a["role"] == "name" and a["plain"]), "без названия")
    who = f"@{user.username}" if user.username else escape(user.first_name or str(user.id))
    html = f"📝 <b>Новая заявка #{app_id}</b>: {escape(name[:64])}\nОт: {who} (<code>{user.id}</code>)"
    await app.notify_admins(html, perm="applications",
                            reply_markup=markup([[button("Открыть заявку", cb=f"a:appl:{app_id}")]]))
    await app.log_event(html)
    return app_id


# ---------- всё остальное от обычных пользователей ----------
@router.message()
async def on_junk(message: Message, app: App, perms: set[str] | None = None) -> None:
    """Держим чат чистым: случайные сообщения пользователей удаляются."""
    if perms is None and app.catalog.setting("clean_chat", 1):
        await safe_delete(app, message.chat.id, message.message_id)
