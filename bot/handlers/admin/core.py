"""Движок админки.

Экраны админки — функции `@view("name")`, открываются кнопкой `a:name:арг1:арг2`.
Действия — `@action("name")`, кнопка `x:name:...`; возвращают callback экрана, куда вернуться.
Ввод текста/медиа — `ctx.ask(...)` + обработчик `@on_input("name")`.
Права проверяются здесь, в одном месте.
"""
import logging
from dataclasses import dataclass, field
from html import escape
from typing import Any, Awaitable, Callable

from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, Message

from ...app import App
from ...catalog import STYLE_NAMES, STYLES, now
from ...media import KIND_NAMES, MediaError
from ...richtext import CAPTION_LIMIT, TEXT_LIMIT, html_to_plain, message_html, parse_label
from ...ui import button, markup, safe_delete

log = logging.getLogger(__name__)
router = Router(name="admin")

PERMS: dict[str, str] = {
    "shops": "🏪 Магазины",
    "applications": "📝 Заявки и анкета",
    "menu": "📋 Меню и кнопки",
    "texts": "📝 Тексты и переводы",
    "cities": "🏙 Города, метки, категории",
    "users": "👥 Пользователи и баны",
    "broadcast": "📣 Рассылка",
    "stats": "📊 Статистика",
    "reports": "🚩 Жалобы",
    "settings": "⚙️ Настройки и защита",
    "backup": "💾 Бэкапы",
    "admins": "👮 Админы",
    "log": "📜 Журнал",
}

Rows = list[list[InlineKeyboardButton]]
ViewResult = tuple[str, Rows]


class InputError(Exception):
    """Ошибка ввода — показывается админу, ввод повторяется."""


class AdminInput(StatesGroup):
    wait = State()


@dataclass
class Ctx:
    app: App
    user_id: int
    chat_id: int
    state: FSMContext
    notice: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    async def toast(self, text: str, alert: bool = False) -> None:
        call = self.extra.get("call")
        if call is not None and not self.extra.get("answered"):
            self.extra["answered"] = True
            await call.answer(text[:190], show_alert=alert)

    async def log(self, action: str, details: str = "") -> None:
        from .journal import describe
        name = await self.app.db.fetchval("SELECT first_name FROM users WHERE id = ?", (self.user_id,))
        pretty = f"{escape(name or str(self.user_id))}: {describe(self.app, action, details)}"
        await self.app.log_action(self.user_id, action, details, pretty)

    async def reload(self) -> None:
        await self.app.catalog.reload()

    async def ask(self, input_name: str, prompt: str, back: str, *args: Any, keep_message: bool = False) -> ViewResult:
        await self.state.set_state(AdminInput.wait)
        await self.state.update_data(input=input_name, args=[str(a) for a in args], back=back, keep=keep_message)
        return prompt, [[button("✖️ Отмена", cb=back)]]


Handler = Callable[..., Awaitable[Any]]
VIEWS: dict[str, tuple[str | None, Handler]] = {}
ACTIONS: dict[str, tuple[str | None, Handler]] = {}
INPUTS: dict[str, tuple[str | None, Handler]] = {}


def view(name: str, perm: str | None = None):
    def deco(fn: Handler) -> Handler:
        VIEWS[name] = (perm, fn)
        return fn
    return deco


def action(name: str, perm: str | None = None):
    def deco(fn: Handler) -> Handler:
        ACTIONS[name] = (perm, fn)
        return fn
    return deco


def on_input(name: str, perm: str | None = None):
    def deco(fn: Handler) -> Handler:
        INPUTS[name] = (perm, fn)
        return fn
    return deco


def allowed(app: App, user_id: int, perm: str | None) -> bool:
    perms = app.perms(user_id)
    if perms is None:
        return False
    return perm is None or "*" in perms or perm in perms


# ---------- показ ----------
admin_screens: dict[int, int] = {}


async def render(ctx: Ctx, result: ViewResult, message_id: int | None) -> None:
    html, rows = result
    if ctx.notice:
        html = f"{ctx.notice}\n\n{html}"
    if len(html) > TEXT_LIMIT:  # резать HTML посередине тега нельзя — показываем простым текстом
        html = escape(html_to_plain(html))[:TEXT_LIMIT - 1] + "…"
    kb = markup(rows)
    bot = ctx.app.bot
    if message_id:
        try:
            await bot.edit_message_text(text=html, chat_id=ctx.chat_id, message_id=message_id, reply_markup=kb)
            admin_screens[ctx.user_id] = message_id
            return
        except TelegramBadRequest as e:
            if "not modified" in e.message:
                return
    msg = await bot.send_message(ctx.chat_id, html, reply_markup=kb)
    old = admin_screens.get(ctx.user_id)
    admin_screens[ctx.user_id] = msg.message_id
    if old and old != msg.message_id:
        await safe_delete(ctx.app, ctx.chat_id, old)
    if message_id and message_id != msg.message_id:
        await safe_delete(ctx.app, ctx.chat_id, message_id)


async def open_view(ctx: Ctx, cb: str) -> ViewResult:
    parts = cb.split(":")
    name, args = (parts[1], parts[2:]) if parts[0] == "a" else ("home", [])
    perm, fn = VIEWS.get(name, VIEWS["home"])
    if not allowed(ctx.app, ctx.user_id, perm):
        perm, fn, args = VIEWS["home"][0], VIEWS["home"][1], []
        ctx.notice = "⛔️ Нет доступа к этому разделу."
    return await fn(ctx, *args)


async def run_action(ctx: Ctx, cb: str) -> ViewResult | None:
    parts = cb.split(":")
    entry = ACTIONS.get(parts[1])
    if entry is None:
        return await open_view(ctx, "a:home")
    perm, fn = entry
    if not allowed(ctx.app, ctx.user_id, perm):
        ctx.notice = "⛔️ Нет доступа."
        return await open_view(ctx, "a:home")
    result = await fn(ctx, *parts[2:])
    if result is None:
        return None
    if isinstance(result, str):
        return await open_view(ctx, result)
    return result


# ---------- хендлеры ----------
@router.message(Command("admin"))
async def cmd_admin(message: Message, state: FSMContext, app: App, perms: set[str] | None = None) -> None:
    if perms is None:
        return  # для остальных команды не существует
    await state.set_state(None)
    await safe_delete(app, message.chat.id, message.message_id)
    ctx = Ctx(app, message.from_user.id, message.chat.id, state)
    await render(ctx, await open_view(ctx, "a:home"), None)


@router.callback_query(F.data.startswith(("a:", "x:")))
async def on_admin_callback(call: CallbackQuery, state: FSMContext, app: App, perms: set[str] | None = None) -> None:
    if perms is None:
        await call.answer()
        return
    await state.set_state(None)
    ctx = Ctx(app, call.from_user.id, call.message.chat.id, state)
    ctx.extra["call"] = call
    msg_id = call.message.message_id if isinstance(call.message, Message) and call.message.text else None
    try:
        if call.data.startswith("a:"):
            result: ViewResult | None = await open_view(ctx, call.data)
        else:
            result = await run_action(ctx, call.data)
    except TelegramAPIError:
        raise
    except Exception as e:  # ошибка в одном экране не должна ронять админку
        log.exception("Ошибка админки на %s", call.data)
        await call.answer(f"Ошибка: {e}"[:190], show_alert=True)
        return
    if result is not None:
        await render(ctx, result, msg_id)
    if not ctx.extra.get("answered"):
        await call.answer()


@router.message(AdminInput.wait, ~F.text.startswith("/"))
async def on_admin_input(message: Message, state: FSMContext, app: App, perms: set[str] | None = None) -> None:
    if perms is None:
        return
    data = await state.get_data()
    ctx = Ctx(app, message.from_user.id, message.chat.id, state)
    screen_id = admin_screens.get(ctx.user_id)
    entry = INPUTS.get(data.get("input", ""))
    if entry is None or not allowed(app, ctx.user_id, entry[0]):
        await state.set_state(None)
        return
    if not data.get("keep"):
        await safe_delete(app, message.chat.id, message.message_id)
    try:
        next_cb = await entry[1](ctx, message, *data.get("args", []))
    except (InputError, MediaError) as e:
        html = f"⚠️ {escape(str(e))}\n\nПопробуйте ещё раз или нажмите ✖️ Отмена."
        await render(ctx, (html, [[button("✖️ Отмена", cb=data.get("back", "a:home"))]]), screen_id)
        return
    except Exception as e:
        log.exception("Ошибка ввода в админке (%s)", data.get("input"))
        await state.set_state(None)
        html = f"⚠️ Ошибка: {escape(str(e))[:300]}"
        await render(ctx, (html, [[button("◀️ Назад", cb=data.get("back", "a:home"))]]), screen_id)
        return
    if await state.get_state() == AdminInput.wait.state and (await state.get_data()).get("input") == data.get("input"):
        await state.set_state(None)
    result = await open_view(ctx, next_cb) if isinstance(next_cb, str) else next_cb
    if data.get("keep"):
        screen_id = None  # сообщение админа осталось в чате — экран присылаем ниже
    await render(ctx, result, screen_id)


# ---------- общие элементы экранов ----------
def back_btn(cb: str, text: str = "◀️ Назад") -> list[InlineKeyboardButton]:
    return [button(text, cb=cb)]


def b(text: str, cb: str, style: str | None = None) -> InlineKeyboardButton:
    return button(text, cb=cb, style=style)


def yes_no(v: Any) -> str:
    return "да" if v else "нет"


def snippet(html: str, limit: int = 300) -> str:
    plain = html_to_plain(html).strip()
    if not plain:
        return "<i>пусто</i>"
    return escape(plain[:limit] + ("…" if len(plain) > limit else ""))


def style_name(style: str | None) -> str:
    return STYLE_NAMES.get(style, style or "обычная")


def next_style(style: str | None) -> str | None:
    i = STYLES.index(style) if style in STYLES else 0
    return STYLES[(i + 1) % len(STYLES)]


def icon_line(icon: str | None) -> str:
    return f'<tg-emoji emoji-id="{icon}">⭐️</tg-emoji> <code>{icon}</code>' if icon else "нет"


def media_line(app: App, media_id: int | None) -> str:
    m = app.media.get(media_id)
    if m is None:
        return "нет"
    state = "" if m.path.exists() else " ⚠️ файл потерян"
    return f"{KIND_NAMES.get(m.kind, m.kind)}, {m.size / 1048576:.1f} МБ{state}"


# ---------- универсальные редакторы ----------
# тип объекта -> (таблица, ключ, экран, право, есть ли текст/медиа)
TARGETS: dict[str, tuple[str, str, str, str, bool]] = {
    "item": ("menu_items", "id", "a:item:{}", "menu", True),
    "text": ("texts", "key", "a:text:{}", "texts", True),
    "btn": ("buttons", "key", "a:btn:{}", "texts", False),
    "city": ("cities", "id", "a:city:{}", "cities", False),
    "shop": ("shops", "id", "a:shop:{}", "shops", True),
    "tag": ("tags", "id", "a:tag:{}", "cities", False),
    "cat": ("categories", "id", "a:catg:{}", "cities", False),
    "field": ("app_fields", "id", "a:fld:{}", "applications", False),
}
# что из объекта можно перевести на другие языки
TR_FIELDS: dict[str, tuple[str, ...]] = {
    "item": ("label", "html"), "text": ("html",), "btn": ("label",), "city": ("label",),
    "shop": ("label", "html"), "tag": ("label",), "cat": ("label",), "field": ("label", "html"),
}


def _target(kind: str, key: str) -> tuple[str, str, str, str, bool, Any]:
    table, pk, screen, perm, rich = TARGETS[kind]
    return table, pk, screen.format(key), perm, rich, (int(key) if pk == "id" else key)


async def _check_target_perm(ctx: Ctx, kind: str) -> None:
    if not allowed(ctx.app, ctx.user_id, TARGETS[kind][3]):
        raise InputError("Нет доступа.")


async def update_target(ctx: Ctx, kind: str, key: str, **fields: Any) -> None:
    table, pk, _, _, _, k = _target(kind, key)
    if table == "shops":
        fields["updated_at"] = now()
    cols = ", ".join(f"{c} = ?" for c in fields)
    await ctx.app.db.execute(f"UPDATE {table} SET {cols} WHERE {pk} = ?", (*fields.values(), k))
    await ctx.reload()


async def fetch_target(ctx: Ctx, kind: str, key: str):
    table, pk, _, _, _, k = _target(kind, key)
    return await ctx.app.db.fetchone(f"SELECT * FROM {table} WHERE {pk} = ?", (k,))


LABEL_HELP = (
    "Отправьте новый текст кнопки.\n"
    "Первое <b>премиум-эмодзи</b> в сообщении станет иконкой кнопки, бот сам возьмёт его ID.\n"
    "Можно прислать только премиум-эмодзи, чтобы поменять одну иконку."
)
HTML_HELP = (
    "Отправьте новый текст. Форматирование, ссылки и <b>премиум-эмодзи</b> сохранятся как есть.\n"
    "Можно прислать фото, GIF или видео с подписью: обновятся и картинка, и текст."
)
MEDIA_HELP = "Пришлите фото, GIF или видео (можно файлом): JPG, PNG, WEBP, GIF, MP4."


@action("lbl")
async def act_label(ctx: Ctx, kind: str, key: str):
    await _check_target_perm(ctx, kind)
    return await ctx.ask("label", LABEL_HELP, TARGETS[kind][2].format(key), kind, key)


@on_input("label")
async def in_label(ctx: Ctx, message: Message, kind: str, key: str):
    await _check_target_perm(ctx, kind)
    if not message.text:
        raise InputError("Нужен текст.")
    label, icon = parse_label(message)
    fields: dict[str, Any] = {}
    if label:
        fields["label"] = label
    if icon and kind not in ("tag", "field"):
        fields["icon"] = icon
    if not fields:
        raise InputError("Пустой текст.")
    await update_target(ctx, kind, key, **fields)
    await ctx.log(f"{kind}.label", f"{key}: {label}")
    ctx.notice = "✅ Сохранено"
    return TARGETS[kind][2].format(key)


@action("sty")
async def act_style(ctx: Ctx, kind: str, key: str):
    await _check_target_perm(ctx, kind)
    row = await fetch_target(ctx, kind, key)
    await update_target(ctx, kind, key, style=next_style(row["style"]))
    return TARGETS[kind][2].format(key)


@action("noico")
async def act_no_icon(ctx: Ctx, kind: str, key: str):
    await _check_target_perm(ctx, kind)
    await update_target(ctx, kind, key, icon=None)
    return TARGETS[kind][2].format(key)


@action("htm")
async def act_html(ctx: Ctx, kind: str, key: str):
    await _check_target_perm(ctx, kind)
    return await ctx.ask("html", HTML_HELP, TARGETS[kind][2].format(key), kind, key)


async def _save_media(ctx: Ctx, message: Message) -> int:
    max_mb = float(ctx.app.catalog.setting("max_media_mb", 10))
    return await ctx.app.media.save_from_message(ctx.app.bot, message, int(max_mb * 1048576))


def _has_media(message: Message) -> bool:
    return bool(message.photo or message.animation or message.video or message.document)


@on_input("html")
async def in_html(ctx: Ctx, message: Message, kind: str, key: str):
    await _check_target_perm(ctx, kind)
    html, plain = message_html(message)
    row = await fetch_target(ctx, kind, key)
    fields: dict[str, Any] = {}
    media_id = row["media_id"] if "media_id" in row.keys() else None
    if _has_media(message) and "media_id" not in row.keys():
        raise InputError("Здесь нужен только текст.")
    if _has_media(message):
        media_id = fields["media_id"] = await _save_media(ctx, message)
    if not plain and "media_id" not in fields:
        raise InputError("Пустой текст.")
    if plain:
        if media_id and len(plain) > CAPTION_LIMIT:
            raise InputError(f"С медиа текст не длиннее {CAPTION_LIMIT} символов (сейчас {len(plain)}). "
                             "Сократите текст или уберите медиа.")
        if len(plain) > TEXT_LIMIT:
            raise InputError(f"Текст не длиннее {TEXT_LIMIT} символов.")
        fields["html"] = html
        if kind == "shop":
            fields["plain"] = plain
    await update_target(ctx, kind, key, **fields)
    await ctx.log(f"{kind}.html", key)
    ctx.notice = "✅ Сохранено"
    return TARGETS[kind][2].format(key)


@action("med")
async def act_media(ctx: Ctx, kind: str, key: str):
    await _check_target_perm(ctx, kind)
    return await ctx.ask("media", MEDIA_HELP, TARGETS[kind][2].format(key), kind, key)


@on_input("media")
async def in_media(ctx: Ctx, message: Message, kind: str, key: str):
    await _check_target_perm(ctx, kind)
    if not _has_media(message):
        raise InputError(MEDIA_HELP)
    row = await fetch_target(ctx, kind, key)
    html, plain = message_html(message)
    current_plain = plain or html_to_plain(row["html"])
    if len(current_plain) > CAPTION_LIMIT:
        raise InputError(f"Текст этого экрана длиннее {CAPTION_LIMIT} символов, с картинкой Telegram его не покажет. "
                         "Сначала сократите текст.")
    fields: dict[str, Any] = {"media_id": await _save_media(ctx, message)}
    if plain:
        fields["html"] = html
        if kind == "shop":
            fields["plain"] = plain
    await update_target(ctx, kind, key, **fields)
    await ctx.log(f"{kind}.media", key)
    ctx.notice = "✅ Медиа сохранено"
    return TARGETS[kind][2].format(key)


@action("mkind")
async def act_media_kind(ctx: Ctx, kind: str, key: str):
    """Видео ↔ GIF: GIF в Telegram крутится сам по кругу, но без звука."""
    await _check_target_perm(ctx, kind)
    row = await fetch_target(ctx, kind, key)
    m = ctx.app.media.get(row["media_id"])
    if m and m.kind in ("video", "animation"):
        new = "animation" if m.kind == "video" else "video"
        await ctx.app.media.set_kind(m.id, new)
        ctx.notice = ("✅ Теперь это GIF: воспроизводится сам, по кругу, без звука." if new == "animation"
                      else "✅ Теперь это видео со звуком: запускается нажатием (или само, если так настроено "
                           "у пользователя в Telegram).")
    return TARGETS[kind][2].format(key)


@action("nomed")
async def act_no_media(ctx: Ctx, kind: str, key: str):
    await _check_target_perm(ctx, kind)
    await update_target(ctx, kind, key, media_id=None)
    await ctx.log(f"{kind}.media_removed", key)
    return TARGETS[kind][2].format(key)


def editor_rows(kind: str, key: str, row: Any, *, label: bool = True, rich: bool = True, app: App | None = None,
                compact: bool = False) -> Rows:
    """Кнопки редактирования: текст и иконка, цвет, текст экрана, картинка.
    compact=True — только основное, остальное (перевод, убрать иконку/медиа) на экране «Ещё»."""
    rows: Rows = []
    if label:
        r = [b("✏️ Текст и иконка", f"x:lbl:{kind}:{key}")]
        if "style" in row.keys():
            r.append(b(f"🎨 Цвет: {style_name(row['style'])}", f"a:col:{kind}:{key}"))
        rows.append(r)
    if rich:
        rows.append([b("📝 Текст экрана" if kind != "shop" else "📝 Текст карточки", f"x:htm:{kind}:{key}"),
                     b("🖼 Картинка / видео", f"x:med:{kind}:{key}")])
    if not compact:
        rows += editor_extras(kind, key, row, app=app, label=label, rich=rich)
    return rows


def editor_extras(kind: str, key: str, row: Any, *, app: App | None = None, label: bool = True,
                  rich: bool = True) -> Rows:
    rows: Rows = []
    if label and "icon" in row.keys() and row["icon"]:
        rows.append([b("✖️ Убрать иконку", f"x:noico:{kind}:{key}")])
    if rich and row["media_id"]:
        m = app.media.get(row["media_id"]) if app else None
        if m and m.kind in ("video", "animation") and m.path.suffix == ".mp4":
            rows.append([b("🔁 Сделать GIF (играет сам, без звука)" if m.kind == "video"
                           else "🔊 Сделать видео со звуком", f"x:mkind:{kind}:{key}")])
        rows.append([b("✖️ Убрать картинку / видео", f"x:nomed:{kind}:{key}")])
    if kind in TR_FIELDS:
        rows.append([b("🌐 Перевод на другие языки", f"a:trl:{kind}:{key}")])
    return rows


COLORS = [(None, "⚪️ Обычная"), ("primary", "🔵 Синяя"), ("success", "🟢 Зелёная"), ("danger", "🔴 Красная")]


@view("col")
async def view_color(ctx: Ctx, kind: str, key: str) -> ViewResult:
    await _check_target_perm(ctx, kind)
    row = await fetch_target(ctx, kind, key)
    rows: Rows = [[button(("✅ " if row["style"] == st else "") + name, style=st, cb=f"x:setsty:{kind}:{key}:{st or 'none'}")]
                  for st, name in COLORS]
    rows.append(back_btn(TARGETS[kind][2].format(key)))
    return "🎨 <b>Цвет кнопки</b>\nНажмите нужный. Каждая кнопка ниже показана своим цветом.", rows


@action("setsty")
async def act_set_style(ctx: Ctx, kind: str, key: str, style: str):
    await _check_target_perm(ctx, kind)
    await update_target(ctx, kind, key, style=None if style == "none" else style)
    ctx.notice = "✅ Цвет сохранён"
    return TARGETS[kind][2].format(key)


# ---------- перестановка ----------
async def move(ctx: Ctx, table: str, item_id: int, delta: int, where: str = "1=1", params: tuple = ()) -> None:
    """Сдвигает запись на delta позиций среди записей `where` (нормализуя позиции)."""
    db = ctx.app.db
    ids = [r["id"] for r in await db.fetchall(f"SELECT id FROM {table} WHERE {where} ORDER BY position, id", params)]
    if item_id not in ids:
        return
    i = ids.index(item_id)
    j = min(max(i + delta, 0), len(ids) - 1)
    ids.insert(j, ids.pop(i))
    await db.executemany(f"UPDATE {table} SET position = ? WHERE id = ?", ((p, x) for p, x in enumerate(ids)))
    await ctx.reload()


@action("close")
async def act_close(ctx: Ctx):
    call: CallbackQuery = ctx.extra["call"]
    await safe_delete(ctx.app, ctx.chat_id, call.message.message_id)
    return None


@view("home")
async def view_home(ctx: Ctx) -> ViewResult:
    app = ctx.app
    perms = app.perms(ctx.user_id) or set()
    new_apps = await app.db.fetchval("SELECT COUNT(*) FROM applications WHERE status = 'new'")
    sections = [
        ("shops", "🏪 Магазины", "a:shops:0"),
        ("applications", f"📝 Заявки{f' ({new_apps})' if new_apps else ''}", "a:appls:new:0"),
        ("menu", "📋 Меню", f"a:item:{app.catalog.root_id}"),
        ("texts", "📝 Тексты и кнопки", "a:texts"),
        ("cities", "🏙 Города", "a:cities:0"),
        ("cities", "🏷 Метки", "a:tags"),
        ("cities", "🗂 Категории", "a:catgs"),
        ("texts", "🌐 Языки", "a:langs"),
        ("users", "👥 Пользователи", "a:users"),
        ("broadcast", "📣 Рассылка", "a:bc"),
        ("stats", "📊 Статистика", "a:stats"),
        ("reports", "🚩 Жалобы", "a:reps:0"),
        ("settings", "🛡 Защита", "a:prot"),
        ("settings", "⚙️ Настройки", "a:set"),
        ("backup", "💾 Бэкап", "a:bak"),
        ("admins", "👮 Админы", "a:admins"),
        ("log", "📜 Журнал", "a:log:0"),
    ]
    btns = [b(t, cb) for p, t, cb in sections if "*" in perms or p in perms]
    rows = [btns[i:i + 2] for i in range(0, len(btns), 2)]
    open_reports = await app.db.fetchval("SELECT COUNT(*) FROM reports WHERE status = 'open'")
    cat = app.catalog
    html = (
        "🛠 <b>Админ-панель</b>\n\n"
        f"Магазинов: <b>{len(cat.all_shops)}</b> активных из {len(cat.shops)}\n"
        f"Пользователей: <b>{len(app.known_users)}</b>\n"
        f"Открытых жалоб: <b>{open_reports}</b>"
    )
    return html, rows
