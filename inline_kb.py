from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from database import get_buttons, get_buttons_per_row


def links_inline_kb() -> InlineKeyboardMarkup | None:
    """Каждая кнопка при нажатии всегда идёт через callback (open_<id>) —
    так бот может показать отдельное сообщение с готовой ссылкой,
    независимо от типа кнопки (direct/generated).

    Количество кнопок в строке (1 или 2) настраивается администратором
    в разделе «⚙️ Настройки» и не зашито в код."""
    buttons = get_buttons()
    if not buttons:
        return None

    per_row = get_buttons_per_row()
    rows = []
    current_row = []
    for b in buttons:
        kwargs = {
            "text": b["title"],
            "callback_data": f"open_{b['id']}",
            "style": b["style"] or "primary",
        }
        if b["icon_custom_emoji_id"]:
            kwargs["icon_custom_emoji_id"] = b["icon_custom_emoji_id"]
        current_row.append(InlineKeyboardButton(**kwargs))
        if len(current_row) >= per_row:
            rows.append(current_row)
            current_row = []
    if current_row:
        rows.append(current_row)

    return InlineKeyboardMarkup(inline_keyboard=rows)


def cancel_kb(cancel_callback: str) -> InlineKeyboardMarkup:
    """Единая клавиатура «❌ Отмена», которая должна быть прикреплена
    к любому шагу любого FSM-сценария в боте."""
    from texts import get_text
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=get_text("admin.cancel", "❌ Отмена"), callback_data=cancel_callback)]
    ])


def with_cancel_row(kb: InlineKeyboardMarkup, cancel_callback: str) -> InlineKeyboardMarkup:
    """Добавляет строку «❌ Отмена» под уже готовой клавиатурой."""
    from texts import get_text
    rows = list(kb.inline_keyboard) + [[InlineKeyboardButton(text=get_text("admin.cancel", "❌ Отмена"), callback_data=cancel_callback)]]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def style_choice_kb(prefix: str, cancel_callback: str | None = None) -> InlineKeyboardMarkup:
    """Клавиатура выбора цвета кнопки (используется и в создании, и в правке)."""
    from texts import get_text
    rows = [
        [InlineKeyboardButton(text=get_text("admin.links_menu.style_primary", "🔵 Синий"), callback_data=f"{prefix}_primary")],
        [InlineKeyboardButton(text=get_text("admin.links_menu.style_success", "🟢 Зелёный"), callback_data=f"{prefix}_success")],
        [InlineKeyboardButton(text=get_text("admin.links_menu.style_danger", "🔴 Красный"), callback_data=f"{prefix}_danger")],
    ]
    if cancel_callback:
        rows.append([InlineKeyboardButton(text=get_text("admin.cancel", "❌ Отмена"), callback_data=cancel_callback)])
    return InlineKeyboardMarkup(inline_keyboard=rows)
