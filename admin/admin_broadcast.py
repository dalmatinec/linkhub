from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext

from database import is_admin, count_broadcasts
from admin_states import AdminBroadcastStates
from broadcast_utils import run_broadcast, format_duration
from inline_kb import cancel_kb
from texts import get_text

router = Router()


def broadcast_menu_kb():
    t = lambda k: get_text(f"admin.broadcast.{k}")
    return types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text=t("menu_new"), callback_data="broadcast_new")],
        [types.InlineKeyboardButton(text=t("menu_history"), callback_data="broadcast_history")],
        [types.InlineKeyboardButton(text=get_text("admin.menu.back"), callback_data="admin_back_to_menu")],
    ])


def confirm_kb():
    t = lambda k: get_text(f"admin.broadcast.{k}")
    return types.InlineKeyboardMarkup(inline_keyboard=[[
        types.InlineKeyboardButton(text=t("send"), callback_data="broadcast_send"),
        types.InlineKeyboardButton(text=t("cancel"), callback_data="broadcast_cancel"),
    ]])


def forward_prompt_kb():
    return cancel_kb("broadcast_cancel")


@router.callback_query(F.data == "admin_broadcast")
async def open_broadcast_menu(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer(get_text("admin.not_admin"), show_alert=True)
        return
    await callback.message.edit_text(get_text("admin.broadcast.title", "📨 Рассылки"), reply_markup=broadcast_menu_kb())
    await callback.answer()


@router.callback_query(F.data == "broadcast_history")
async def broadcast_history(callback: types.CallbackQuery):
    count = count_broadcasts()
    if count == 0:
        await callback.message.answer(get_text("admin.broadcast.history_empty"))
    else:
        await callback.message.answer(get_text("admin.broadcast.history_template", count=count, last_date="—"))
    await callback.answer()


@router.callback_query(F.data == "broadcast_new")
async def broadcast_new(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(AdminBroadcastStates.waiting_forward)
    await callback.message.answer(get_text("admin.broadcast.ask_forward"), reply_markup=forward_prompt_kb())
    await callback.answer()


@router.message(AdminBroadcastStates.waiting_forward)
async def broadcast_preview(message: types.Message, state: FSMContext):
    await state.update_data(from_chat_id=message.chat.id, message_id=message.message_id)
    await state.set_state(AdminBroadcastStates.waiting_confirm)
    await message.answer(get_text("admin.broadcast.preview_title"))
    await message.bot.copy_message(message.chat.id, message.chat.id, message.message_id)
    # Раньше здесь отправлялось сообщение с одним пробелом, из-за чего
    # Telegram возвращал ошибку "text must be non-empty" — заменено
    # на нормальный текст-подсказку с кнопками "✅ Отправить" / "❌ Отмена".
    await message.answer(get_text("admin.broadcast.confirm_prompt"), reply_markup=confirm_kb())


@router.callback_query(F.data == "broadcast_cancel")
async def broadcast_cancel(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.answer(get_text("admin.broadcast.cancelled"))
    await callback.message.answer(get_text("admin.broadcast.title", "📨 Рассылки"), reply_markup=broadcast_menu_kb())
    await callback.answer()


@router.callback_query(AdminBroadcastStates.waiting_confirm, F.data == "broadcast_send")
async def broadcast_send(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    await state.clear()
    await callback.message.answer(get_text("admin.broadcast.started"))
    await callback.answer()

    result = await run_broadcast(callback.bot, data["from_chat_id"], data["message_id"])
    await callback.message.answer(get_text(
        "admin.broadcast.report",
        total=result["total"],
        sent=result["sent"],
        failed=result["failed"],
        duration=format_duration(result["duration_seconds"])
    ))
