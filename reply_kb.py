from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from texts import get_text


def main_reply_kb() -> ReplyKeyboardMarkup:
    row = [
        KeyboardButton(text=get_text("menu.links_button", "🔗 Актуальные ссылки")),
        KeyboardButton(text=get_text("menu.settings_button", "⚙️ Настройки")),
    ]
    return ReplyKeyboardMarkup(keyboard=[row], resize_keyboard=True)
