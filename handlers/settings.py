from aiogram import Router, F, types

from database import get_user, set_push
from texts import get_text

router = Router()


def _settings_kb():
    push_label = get_text("settings.push_button", "🔔 Push-уведомления")
    lang_label = get_text("settings.language_button", "🌐 Язык")
    return types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text=lang_label, callback_data="settings_language")],
        [types.InlineKeyboardButton(text=push_label, callback_data="settings_push")],
    ])


@router.message(F.text == get_text("menu.settings_button", "⚙️ Настройки"))
async def show_settings(message: types.Message):
    await message.answer(get_text("settings.title", "⚙️ Настройки"), reply_markup=_settings_kb())


@router.callback_query(F.data == "settings_language")
async def settings_language(callback: types.CallbackQuery):
    await callback.answer(get_text("settings.language_stub", "🌐 Пока доступен только русский язык."), show_alert=True)


@router.callback_query(F.data == "settings_push")
async def settings_push(callback: types.CallbackQuery):
    user = get_user(callback.from_user.id)
    currently_on = bool(user["push_enabled"]) if user else True

    kb = types.InlineKeyboardMarkup(inline_keyboard=[[
        types.InlineKeyboardButton(
            text=get_text("settings.push_off", "❌ Выключить") if currently_on else get_text("settings.push_on", "✅ Включить"),
            callback_data="settings_push_toggle"
        )
    ]])
    status = get_text("settings.push_enabled_msg") if currently_on else get_text("settings.push_disabled_msg")
    await callback.message.edit_text(status, reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data == "settings_push_toggle")
async def settings_push_toggle(callback: types.CallbackQuery):
    user = get_user(callback.from_user.id)
    currently_on = bool(user["push_enabled"]) if user else True
    set_push(callback.from_user.id, not currently_on)

    kb = types.InlineKeyboardMarkup(inline_keyboard=[[
        types.InlineKeyboardButton(
            text=get_text("settings.push_on", "✅ Включить") if currently_on else get_text("settings.push_off", "❌ Выключить"),
            callback_data="settings_push_toggle"
        )
    ]])
    status = get_text("settings.push_disabled_msg") if currently_on else get_text("settings.push_enabled_msg")
    await callback.message.edit_text(status, reply_markup=kb)
    await callback.answer()
