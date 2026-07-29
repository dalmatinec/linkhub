from aiogram import Router, F, types
from aiogram.filters import Command

from database import is_admin
from texts import get_text

router = Router()


def admin_menu_kb():
    t = lambda k: get_text(f"admin.menu.{k}")
    return types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text=t("broadcast"), callback_data="admin_broadcast")],
        [types.InlineKeyboardButton(text=t("start_message"), callback_data="admin_start_message")],
        [types.InlineKeyboardButton(text=t("links"), callback_data="admin_links")],
        [types.InlineKeyboardButton(text=t("admins"), callback_data="admin_admins")],
        [types.InlineKeyboardButton(text=t("stats"), callback_data="admin_stats")],
        [types.InlineKeyboardButton(text=t("settings"), callback_data="admin_settings")],
    ])


@router.message(Command("admin"))
@router.message(F.text.lower() == "админ")
async def open_admin(message: types.Message):
    if not is_admin(message.from_user.id):
        await message.answer(get_text("admin.not_admin", "⛔ У вас нет доступа к админ-панели."))
        return
    await message.answer(get_text("admin.menu_title", "👑 Админ-панель"), reply_markup=admin_menu_kb())


@router.callback_query(F.data == "admin_back_to_menu")
async def back_to_menu(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer(get_text("admin.not_admin"), show_alert=True)
        return
    await callback.message.edit_text(get_text("admin.menu_title", "👑 Админ-панель"), reply_markup=admin_menu_kb())
    await callback.answer()
