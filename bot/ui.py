"""Сборка клавиатур и показ экранов: редактируем текущее сообщение, где это возможно,
иначе отправляем новое и удаляем старое — в личке всегда один экран бота."""
import logging
from html import escape
from typing import Callable, Sequence, TypeVar

from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from .app import App, Screen

log = logging.getLogger(__name__)

T = TypeVar("T")
BLANK = "⠀"  # Telegram не принимает пустой текст


# Подстановки в текстах: в админке пишутся по-русски, английские оставлены для совместимости
PLACEHOLDERS = {"first_name": "имя", "city": "город", "query": "запрос", "shop": "магазин"}


def fill(html: str, **values: object) -> str:
    """Подставляет {имя}, {город}… в HTML-текст из базы, экранируя значения."""
    for key, value in values.items():
        safe = escape(str(value))
        html = html.replace("{" + key + "}", safe)
        if key in PLACEHOLDERS:
            html = html.replace("{" + PLACEHOLDERS[key] + "}", safe)
    return html


def button(label: str, icon: str | None = None, style: str | None = None, *, cb: str | None = None,
           url: str | None = None) -> InlineKeyboardButton:
    return InlineKeyboardButton(
        text=label or BLANK, icon_custom_emoji_id=icon or None, style=style or None, callback_data=cb, url=url
    )


def sys_button(app: App, key: str, cb: str) -> InlineKeyboardButton:
    b = app.catalog.button(key)
    return button(b.label, b.icon, b.style, cb=cb)


def grid(buttons: Sequence[InlineKeyboardButton], per_row: int) -> list[list[InlineKeyboardButton]]:
    per_row = max(1, min(per_row, 8))
    return [list(buttons[i:i + per_row]) for i in range(0, len(buttons), per_row)]


def paginate(items: Sequence[T], page: int, size: int) -> tuple[Sequence[T], int, int]:
    size = max(1, size)
    pages = max(1, -(-len(items) // size))
    page = min(max(page, 0), pages - 1)
    return items[page * size:(page + 1) * size], page, pages


def nav_row(app: App, page: int, pages: int, make_cb: Callable[[int], str]) -> list[InlineKeyboardButton]:
    if pages <= 1:
        return []
    row = []
    if page > 0:
        row.append(sys_button(app, "prev", make_cb(page - 1)))
    row.append(button(f"{page + 1}/{pages}", cb="noop"))
    if page < pages - 1:
        row.append(sys_button(app, "next", make_cb(page + 1)))
    return row


def markup(rows: list[list[InlineKeyboardButton]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[r for r in rows if r])


async def show(
    app: App, user_id: int, chat_id: int, html: str, media_id: int | None,
    kb: InlineKeyboardMarkup | None, *, current: Screen | None = None,
) -> None:
    """Показать экран. `current` — сообщение, которое можно отредактировать (обычно — нажатое)."""
    bot = app.bot
    media = app.media.get(media_id)
    html = html or BLANK
    if current is not None:
        try:
            if media and current.has_media:
                if await app.media.edit(bot, chat_id, current.message_id, media.id, html, kb):
                    app.set_screen(user_id, current.message_id, True)
                    return
            elif not media and not current.has_media:
                await bot.edit_message_text(text=html, chat_id=chat_id, message_id=current.message_id, reply_markup=kb)
                app.set_screen(user_id, current.message_id, False)
                return
        except TelegramBadRequest as e:
            if "not modified" in e.message:
                app.set_screen(user_id, current.message_id, current.has_media)
                return
            log.debug("Редактирование не удалось (%s), отправляю заново", e.message)

    old_id = current.message_id if current is not None else await app.last_screen_id(user_id)
    msg: Message | None = None
    if media:
        msg = await app.media.send(bot, chat_id, media.id, html, kb)
    if msg is None:
        msg = await bot.send_message(chat_id, html, reply_markup=kb)
    app.set_screen(user_id, msg.message_id, media is not None and msg.content_type != "text")
    if old_id and old_id != msg.message_id:
        await safe_delete(app, chat_id, old_id)


def current_of(message: object) -> Screen | None:
    """Экран из нажатого сообщения. Недоступное (старше 48 ч) не редактируем — пришлём новое."""
    if not isinstance(message, Message):
        return None
    return Screen(message.message_id, bool(message.photo or message.animation or message.video or message.document))


async def safe_delete(app: App, chat_id: int, message_id: int) -> None:
    try:
        await app.bot.delete_message(chat_id, message_id)
    except TelegramAPIError:
        pass  # старше 48 часов или уже удалено
