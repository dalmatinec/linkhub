"""Пользовательская часть. Все тексты/кнопки берутся из кэша каталога.

Callback-данные (≤64 байт):
  m:<item>                 пункт меню
  l:<item>:<page>          список магазинов пункта (метка / все)
  o:<item>:<page>          другие города
  y:<city>:<item>:<page>   магазины города
  s:<shop>:<ctx>           карточка; ctx — куда вести «Назад» (m1, l5.0, y3.4.0, q0)
  q:<page>                 результаты поиска
  r:<shop>:<ctx>           жалоба
"""
from html import escape

from aiogram import F, Router
from aiogram.filters import CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, Message

from ..app import App
from ..catalog import MenuItem, Shop, now
from ..richtext import html_to_plain
from ..ui import button, current_of, fill, grid, markup, nav_row, paginate, safe_delete, show, sys_button

router = Router(name="user")


class Search(StatesGroup):
    query = State()


class Report(StatesGroup):
    text = State()


def ctx_to_cb(ctx: str) -> str:
    return f"{ctx[0]}:{ctx[1:].replace('.', ':')}" if ctx else "m:0"


# ---------- сборка экранов ----------
def item_button(item: MenuItem) -> InlineKeyboardButton:
    if item.kind == "url":
        return button(item.label, item.icon, item.style, url=item.payload or "https://t.me")
    return button(item.label, item.icon, item.style, cb=f"m:{item.id}")


def back_to_parent(app: App, item: MenuItem) -> list[InlineKeyboardButton]:
    if item.parent_id is None:
        return []
    return [sys_button(app, "back", f"m:{item.parent_id}")]


def screen_menu(app: App, item: MenuItem, first_name: str):
    rows: dict[int, list[InlineKeyboardButton]] = {}
    for child in app.catalog.active_children(item.id):
        rows.setdefault(child.row, []).append(item_button(child))
    kb = [rows[r] for r in sorted(rows)]
    kb.append(back_to_parent(app, item))
    return fill(item.html, first_name=first_name), item.media_id, markup(kb)


def shop_buttons(shops: list[Shop], ctx: str) -> list[InlineKeyboardButton]:
    return [button(s.label, s.icon, s.style, cb=f"s:{s.id}:{ctx}") for s in shops]


def screen_shop_list(app: App, item: MenuItem, page: int):
    cat = app.catalog
    shops = cat.all_shops if item.kind == "all" else cat.by_tag.get(int(item.payload or 0), [])
    chunk, page, pages = paginate(shops, page, int(cat.setting("page_size", 10)))
    html = item.html or item.label
    if not shops:
        html += "\n\n" + cat.text("empty").html
    kb = grid(shop_buttons(list(chunk), f"l{item.id}.{page}"), int(cat.setting("per_row", 2)))
    kb.append(nav_row(app, page, pages, lambda p: f"l:{item.id}:{p}"))
    kb.append(back_to_parent(app, item))
    return html, item.media_id, markup(kb)


def screen_cities(app: App, item: MenuItem):
    cat = app.catalog
    btns = [button(c.label, c.icon, c.style, cb=f"y:{c.id}:{item.id}:0") for c in cat.main_cities]
    if cat.other_cities:
        btns.append(sys_button(app, "other_cities", f"o:{item.id}:0"))
    kb = grid(btns, int(cat.setting("per_row", 2)))
    kb.append(back_to_parent(app, item))
    t = cat.text("cities")
    return item.html or t.html, item.media_id or t.media_id, markup(kb)


def screen_other_cities(app: App, item_id: int, page: int):
    cat = app.catalog
    chunk, page, pages = paginate(cat.other_cities, page, int(cat.setting("page_size", 10)))
    btns = [button(c.label, c.icon, c.style, cb=f"y:{c.id}:{item_id}:0") for c in chunk]
    kb = grid(btns, int(cat.setting("per_row", 2)))
    kb.append(nav_row(app, page, pages, lambda p: f"o:{item_id}:{p}"))
    kb.append([sys_button(app, "back", f"m:{item_id}")])
    t = cat.text("other_cities")
    return t.html, t.media_id, markup(kb)


def screen_city(app: App, city_id: int, item_id: int, page: int):
    cat = app.catalog
    city = cat.cities.get(city_id)
    if city is None:
        return None
    shops = cat.by_city.get(city_id, [])
    chunk, page, pages = paginate(shops, page, int(cat.setting("page_size", 10)))
    t = cat.text("city_shops")
    html = fill(t.html, city=city.label)
    if not shops:
        html += "\n\n" + cat.text("empty").html
    kb = grid(shop_buttons(list(chunk), f"y{city_id}.{item_id}.{page}"), int(cat.setting("per_row", 2)))
    kb.append(nav_row(app, page, pages, lambda p: f"y:{city_id}:{item_id}:{p}"))
    if city.is_main or city not in cat.other_cities:
        back = f"m:{item_id}"
    else:
        size = max(1, int(cat.setting("page_size", 10)))
        back = f"o:{item_id}:{cat.other_cities.index(city) // size}"
    kb.append([sys_button(app, "back", back)])
    return html, t.media_id, markup(kb)


def screen_card(app: App, shop: Shop, ctx: str):
    cat = app.catalog
    html = shop.html or shop.label
    if shop.verified:
        html = cat.text("verified_badge").html + "\n\n" + html
    kb = [[button(c.label, c.icon, c.style, url=c.url)] for c in shop.contacts]
    kb.append([sys_button(app, "report", f"r:{shop.id}:{ctx}")])
    kb.append([sys_button(app, "back", ctx_to_cb(ctx))])
    return html, shop.media_id, markup(kb)


def screen_search_results(app: App, query: str, page: int):
    cat = app.catalog
    results = cat.search(query)
    chunk, page, pages = paginate(results, page, int(cat.setting("page_size", 10)))
    key = "search_results" if results else "search_empty"
    kb = grid(shop_buttons(list(chunk), f"q{page}"), int(cat.setting("per_row", 2)))
    kb.append(nav_row(app, page, pages, lambda p: f"q:{p}"))
    search_item = next((i for i in cat.menu.values() if i.kind == "search" and i.is_active), None)
    back = f"m:{search_item.parent_id}" if search_item and search_item.parent_id else f"m:{cat.root_id}"
    kb.append([sys_button(app, "back", back)])
    return fill(cat.text(key).html, query=query), None, markup(kb)


# ---------- /start ----------
@router.message(CommandStart())
async def cmd_start(message: Message, command: CommandObject, state: FSMContext, app: App) -> None:
    await state.clear()
    user = message.from_user
    await safe_delete(app, message.chat.id, message.message_id)
    arg = command.args or ""
    if arg.startswith("shop_") and arg[5:].isdigit():
        shop = app.catalog.shops.get(int(arg[5:]))
        if shop and shop.is_active:
            app.track(shop.id, user.id)
            await show(app, user.id, message.chat.id, *screen_card(app, shop, f"m{app.catalog.root_id}"))
            return
    root = app.catalog.menu.get(app.catalog.root_id)
    if root is None:
        await message.answer("Бот ещё не настроен.")
        return
    await show(app, user.id, message.chat.id, *screen_menu(app, root, user.first_name or ""))


# ---------- навигация ----------
@router.callback_query(F.data.startswith("m:"))
async def cb_menu(call: CallbackQuery, state: FSMContext, app: App) -> None:
    cat = app.catalog
    item_id = int(call.data[2:]) or cat.root_id
    item = cat.menu.get(item_id)
    if item is None or not item.is_active:
        item = cat.menu[cat.root_id]
    await state.set_state(None)
    cur = current_of(call.message)
    uid, chat_id = call.from_user.id, call.message.chat.id
    if item.kind in ("tag", "all"):
        await show(app, uid, chat_id, *screen_shop_list(app, item, 0), current=cur)
    elif item.kind == "cities":
        await show(app, uid, chat_id, *screen_cities(app, item), current=cur)
    elif item.kind == "search":
        await state.set_state(Search.query)
        t = cat.text("search_prompt")
        kb = markup([back_to_parent(app, item)])
        await show(app, uid, chat_id, item.html or t.html, item.media_id or t.media_id, kb, current=cur)
    else:
        await show(app, uid, chat_id, *screen_menu(app, item, call.from_user.first_name or ""), current=cur)
    await call.answer()


@router.callback_query(F.data.startswith("l:"))
async def cb_list(call: CallbackQuery, state: FSMContext, app: App) -> None:
    _, item_id, page = call.data.split(":")
    item = app.catalog.menu.get(int(item_id))
    if item is None or item.kind not in ("tag", "all"):
        return await cb_home(call, state, app)
    await state.set_state(None)
    await show(app, call.from_user.id, call.message.chat.id, *screen_shop_list(app, item, int(page)),
               current=current_of(call.message))
    await call.answer()


@router.callback_query(F.data.startswith("o:"))
async def cb_other_cities(call: CallbackQuery, state: FSMContext, app: App) -> None:
    _, item_id, page = call.data.split(":")
    await state.set_state(None)
    await show(app, call.from_user.id, call.message.chat.id, *screen_other_cities(app, int(item_id), int(page)),
               current=current_of(call.message))
    await call.answer()


@router.callback_query(F.data.startswith("y:"))
async def cb_city(call: CallbackQuery, state: FSMContext, app: App) -> None:
    _, city_id, item_id, page = call.data.split(":")
    screen = screen_city(app, int(city_id), int(item_id), int(page))
    if screen is None:
        return await cb_home(call, state, app)
    await state.set_state(None)
    await show(app, call.from_user.id, call.message.chat.id, *screen, current=current_of(call.message))
    await call.answer()


@router.callback_query(F.data.startswith("s:"))
async def cb_shop(call: CallbackQuery, state: FSMContext, app: App) -> None:
    _, shop_id, ctx = call.data.split(":", 2)
    shop = app.catalog.shops.get(int(shop_id))
    if shop is None or not shop.is_active:
        await call.answer(html_to_plain(app.catalog.text("shop_unavailable").html)[:190], show_alert=True)
        return
    await state.set_state(None)
    app.track(shop.id, call.from_user.id)
    await show(app, call.from_user.id, call.message.chat.id, *screen_card(app, shop, ctx),
               current=current_of(call.message))
    await call.answer()


@router.callback_query(F.data.startswith("q:"))
async def cb_search_page(call: CallbackQuery, state: FSMContext, app: App) -> None:
    query = (await state.get_data()).get("query")
    if not query:
        return await cb_home(call, state, app)
    await state.set_state(Search.query)
    await show(app, call.from_user.id, call.message.chat.id,
               *screen_search_results(app, query, int(call.data[2:])), current=current_of(call.message))
    await call.answer()


@router.callback_query(F.data == "noop")
async def cb_noop(call: CallbackQuery) -> None:
    await call.answer()


async def cb_home(call: CallbackQuery, state: FSMContext, app: App) -> None:
    await state.set_state(None)
    root = app.catalog.menu[app.catalog.root_id]
    await show(app, call.from_user.id, call.message.chat.id,
               *screen_menu(app, root, call.from_user.first_name or ""), current=current_of(call.message))
    await call.answer()


# ---------- поиск ----------
@router.message(Search.query, F.text)
async def on_search(message: Message, state: FSMContext, app: App) -> None:
    await safe_delete(app, message.chat.id, message.message_id)
    query = " ".join(message.text.split())[:64]
    await state.update_data(query=query)
    await show(app, message.from_user.id, message.chat.id, *screen_search_results(app, query, 0),
               current=app.screens.get(message.from_user.id))


# ---------- жалобы ----------
@router.callback_query(F.data.startswith("r:"))
async def cb_report(call: CallbackQuery, state: FSMContext, app: App) -> None:
    _, shop_id, ctx = call.data.split(":", 2)
    shop = app.catalog.shops.get(int(shop_id))
    if shop is None:
        return await cb_home(call, state, app)
    cooldown = int(app.catalog.setting("report_cooldown_minutes", 60)) * 60
    last = await app.db.fetchval("SELECT MAX(created_at) FROM reports WHERE user_id = ?", (call.from_user.id,))
    if last and now() - last < cooldown:
        await call.answer(html_to_plain(app.catalog.text("report_limit").html)[:190], show_alert=True)
        return
    await state.set_state(Report.text)
    await state.update_data(report_shop=shop.id, report_ctx=ctx)
    kb = markup([[sys_button(app, "back", f"s:{shop.id}:{ctx}")]])
    await show(app, call.from_user.id, call.message.chat.id,
               fill(app.catalog.text("report_prompt").html, shop=shop.label), None, kb,
               current=current_of(call.message))
    await call.answer()


@router.message(Report.text, F.text)
async def on_report(message: Message, state: FSMContext, app: App) -> None:
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
    kb = markup([[sys_button(app, "back", f"s:{shop.id}:{data.get('report_ctx', 'm0')}")]])
    await show(app, message.from_user.id, message.chat.id, app.catalog.text("report_thanks").html, None, kb,
               current=app.screens.get(message.from_user.id))
    await app.notify_admins(
        f"🚩 <b>Жалоба #{report_id}</b> на «{escape(shop.label)}»\n"
        f"От: <code>{message.from_user.id}</code>\n\n{escape(message.text[:1000])}",
        perm="reports",
        reply_markup=markup([[button("Открыть", cb=f"a:rep:{report_id}")]]),
    )


# ---------- всё остальное от обычных пользователей ----------
@router.message()
async def on_junk(message: Message, app: App, perms: set[str] | None = None) -> None:
    """Держим чат чистым: случайные сообщения пользователей удаляются."""
    if perms is None and app.catalog.setting("clean_chat", 1):
        await safe_delete(app, message.chat.id, message.message_id)

