from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext

from config import SUPER_ADMIN_ID
from database import is_admin, add_admin, remove_admin, list_admins
from admin_states import AdminUserStates
from inline_kb import cancel_kb
from texts import get_text

router = Router()


@router.callback_query(F.data == "cancel_users")
async def cancel_users_flow(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.answer(get_text("admin.cancelled", "✅ Действие отменено."))
    await callback.message.answer(get_text("admin.users.title", "👤 Администраторы"), reply_markup=users_menu_kb())
    await callback.answer()


def users_menu_kb():
    t = lambda k: get_text(f"admin.users.{k}")
    return types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text=t("menu_add"), callback_data="users_add")],
        [types.InlineKeyboardButton(text=t("menu_remove"), callback_data="users_remove")],
        [types.InlineKeyboardButton(text=t("menu_list"), callback_data="users_list")],
        [types.InlineKeyboardButton(text=get_text("admin.menu.back"), callback_data="admin_back_to_menu")],
    ])


@router.callback_query(F.data == "admin_admins")
async def open_users_menu(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer(get_text("admin.not_admin"), show_alert=True)
        return
    await callback.message.edit_text(get_text("admin.users.title", "👤 Администраторы"), reply_markup=users_menu_kb())
    await callback.answer()


@router.callback_query(F.data == "users_list")
async def users_list(callback: types.CallbackQuery):
    ids = [SUPER_ADMIN_ID] + list_admins()
    lines = "\n".join(f"• {i}" + (" (Super Admin)" if i == SUPER_ADMIN_ID else "") for i in ids)
    await callback.message.answer(get_text("admin.users.list_template", list=lines))
    await callback.answer()


@router.callback_query(F.data == "users_add")
async def users_add_start(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id != SUPER_ADMIN_ID:
        await callback.answer(get_text("admin.users.only_super_admin"), show_alert=True)
        return
    await state.set_state(AdminUserStates.waiting_add_id)
    await callback.message.answer(get_text("admin.users.ask_add_id"), reply_markup=cancel_kb("cancel_users"))
    await callback.answer()


@router.message(AdminUserStates.waiting_add_id)
async def users_add_save(message: types.Message, state: FSMContext):
    try:
        new_id = int(message.text.strip())
    except ValueError:
        await message.answer(get_text("admin.users.ask_add_id"), reply_markup=cancel_kb("cancel_users"))
        return
    add_admin(new_id)
    await state.clear()
    await message.answer(get_text("admin.users.added", id=new_id))


@router.callback_query(F.data == "users_remove")
async def users_remove_start(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id != SUPER_ADMIN_ID:
        await callback.answer(get_text("admin.users.only_super_admin"), show_alert=True)
        return
    await state.set_state(AdminUserStates.waiting_remove_id)
    await callback.message.answer(get_text("admin.users.ask_remove_id"), reply_markup=cancel_kb("cancel_users"))
    await callback.answer()


@router.message(AdminUserStates.waiting_remove_id)
async def users_remove_save(message: types.Message, state: FSMContext):
    try:
        rm_id = int(message.text.strip())
    except ValueError:
        await message.answer(get_text("admin.users.ask_remove_id"), reply_markup=cancel_kb("cancel_users"))
        return
    remove_admin(rm_id)
    await state.clear()
    await message.answer(get_text("admin.users.removed", id=rm_id))
