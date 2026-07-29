from aiogram import Router, F, types

from database import is_admin, get_buttons_per_row, set_buttons_per_row
from texts import get_text

router = Router()


def settings_menu_kb():
    t = lambda k: get_text(f"admin.settings.{k}")
    current = get_buttons_per_row()
    mark_1 = "✅ " if current == 1 else ""
    mark_2 = "✅ " if current == 2 else ""
    return types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text=f"{mark_1}{t('set_1')}", callback_data="settings_layout_1")],
        [types.InlineKeyboardButton(text=f"{mark_2}{t('set_2')}", callback_data="settings_layout_2")],
        [types.InlineKeyboardButton(text=get_text("admin.menu.back"), callback_data="admin_back_to_menu")],
    ])


@router.callback_query(F.data == "admin_settings")
async def open_settings(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer(get_text("admin.not_admin"), show_alert=True)
        return
    count = get_buttons_per_row()
    await callback.message.edit_text(
        get_text("admin.settings.buttons_layout", count=count),
        reply_markup=settings_menu_kb(),
    )
    await callback.answer()


@router.callback_query(F.data.in_({"settings_layout_1", "settings_layout_2"}))
async def set_layout(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer(get_text("admin.not_admin"), show_alert=True)
        return
    count = 2 if callback.data == "settings_layout_2" else 1
    set_buttons_per_row(count)
    await callback.message.edit_text(
        get_text("admin.settings.buttons_layout", count=count),
        reply_markup=settings_menu_kb(),
    )
    await callback.answer(get_text("admin.settings.layout_saved", count=count))
