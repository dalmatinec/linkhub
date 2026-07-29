from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext

from database import is_admin, get_start_message, update_start_message
from admin_states import AdminStartStates
from emoji_utils import extract_custom_emoji_id
from inline_kb import cancel_kb
from texts import get_text
from admin.admin_menu import admin_menu_kb

router = Router()


def start_menu_kb():
    t = lambda k: get_text(f"admin.start_menu.{k}")
    return types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text=t("edit_text"), callback_data="start_edit_text")],
        [types.InlineKeyboardButton(text=t("edit_photo"), callback_data="start_edit_photo")],
        [types.InlineKeyboardButton(text=t("delete_photo"), callback_data="start_delete_photo")],
        [types.InlineKeyboardButton(text=t("edit_emoji"), callback_data="start_edit_emoji")],
        [types.InlineKeyboardButton(text=t("edit_duration"), callback_data="start_edit_duration")],
        [types.InlineKeyboardButton(text=t("view"), callback_data="start_view")],
        [types.InlineKeyboardButton(text=get_text("admin.menu.back"), callback_data="admin_back_to_menu")],
    ])


def duration_kb():
    return types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="15 минут", callback_data="duration_15")],
        [types.InlineKeyboardButton(text="30 минут", callback_data="duration_30")],
        [types.InlineKeyboardButton(text="1 час", callback_data="duration_60")],
        [types.InlineKeyboardButton(text=get_text("admin.cancel", "❌ Отмена"), callback_data="cancel_start")],
    ])


@router.callback_query(F.data == "cancel_start")
async def cancel_start_flow(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.answer(get_text("admin.cancelled", "✅ Действие отменено."))
    await callback.message.answer(get_text("admin.start_menu.title", "🖼 Стартовое сообщение"), reply_markup=start_menu_kb())
    await callback.answer()


@router.callback_query(F.data == "admin_start_message")
async def open_start_menu(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer(get_text("admin.not_admin"), show_alert=True)
        return
    await callback.message.edit_text(get_text("admin.start_menu.title", "🖼 Стартовое сообщение"), reply_markup=start_menu_kb())
    await callback.answer()


@router.callback_query(F.data == "start_view")
async def view_start(callback: types.CallbackQuery):
    sm = get_start_message()
    text = sm["text"] or "(текст не задан)"
    info = (
        f"{text}\n\n"
        f"📷 Фото: {'есть' if sm['photo_file_id'] else 'нет'}\n"
        f"😀 Эмодзи ID: {sm['icon_custom_emoji_id'] or '—'}\n"
        f"⏳ Время действия ссылок: {sm['link_duration_minutes']} мин"
    )
    await callback.message.answer(info)
    await callback.answer()


@router.callback_query(F.data == "start_edit_text")
async def ask_text(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(AdminStartStates.waiting_text)
    await callback.message.answer(get_text("admin.prompts.send_text"), reply_markup=cancel_kb("cancel_start"))
    await callback.answer()


@router.message(AdminStartStates.waiting_text)
async def save_text(message: types.Message, state: FSMContext):
    update_start_message(text=message.text)
    await state.clear()
    await message.answer(get_text("admin.prompts.text_saved"))


@router.callback_query(F.data == "start_edit_photo")
async def ask_photo(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(AdminStartStates.waiting_photo)
    await callback.message.answer(get_text("admin.prompts.send_photo"), reply_markup=cancel_kb("cancel_start"))
    await callback.answer()


@router.message(AdminStartStates.waiting_photo, F.photo)
async def save_photo(message: types.Message, state: FSMContext):
    file_id = message.photo[-1].file_id
    update_start_message(photo_file_id=file_id)
    await state.clear()
    await message.answer(get_text("admin.prompts.photo_saved"))


@router.callback_query(F.data == "start_delete_photo")
async def delete_photo(callback: types.CallbackQuery):
    update_start_message(photo_file_id=None)
    await callback.message.answer(get_text("admin.prompts.photo_deleted"))
    await callback.answer()


@router.callback_query(F.data == "start_edit_emoji")
async def ask_emoji(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(AdminStartStates.waiting_emoji)
    await callback.message.answer(get_text("admin.prompts.send_emoji"), reply_markup=cancel_kb("cancel_start"))
    await callback.answer()


@router.message(AdminStartStates.waiting_emoji)
async def save_emoji(message: types.Message, state: FSMContext):
    emoji_id = extract_custom_emoji_id(message)
    if not emoji_id:
        await message.answer(get_text("admin.prompts.emoji_not_found"), reply_markup=cancel_kb("cancel_start"))
        return
    update_start_message(icon_custom_emoji_id=emoji_id)
    await state.clear()
    await message.answer(get_text("admin.prompts.emoji_saved"))


@router.callback_query(F.data == "start_edit_duration")
async def ask_duration(callback: types.CallbackQuery):
    await callback.message.answer(get_text("admin.prompts.choose_duration"), reply_markup=duration_kb())
    await callback.answer()


@router.callback_query(F.data.startswith("duration_"))
async def save_duration(callback: types.CallbackQuery):
    minutes = int(callback.data.replace("duration_", ""))
    update_start_message(link_duration_minutes=minutes)
    await callback.message.answer(get_text("admin.prompts.duration_saved", minutes=minutes))
    await callback.answer()
