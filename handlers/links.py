from aiogram import Router, F, types

from database import get_button, get_start_message
from link_generator import create_invite_link
from texts import get_text

router = Router()


@router.message(F.text == get_text("menu.links_button", "🔗 Актуальные ссылки"))
async def show_links(message: types.Message):
    # Стартовое сообщение — основная карточка бота: при нажатии
    # «🔗 Актуальные ссылки» бот заново отправляет именно её,
    # с теми же inline-кнопками. Отдельного сообщения "Выберите ссылку"
    # больше не существует.
    from handlers.start import send_main_menu
    await send_main_menu(message)


@router.callback_query(F.data.startswith("open_"))
async def open_link(callback: types.CallbackQuery):
    button_id = int(callback.data.replace("open_", ""))
    btn = get_button(button_id)

    if not btn:
        await callback.answer(get_text("links.button_not_found", "❌ Кнопка не найдена"), show_alert=True)
        return

    if btn["type"] == "direct":
        kb = types.InlineKeyboardMarkup(inline_keyboard=[[
            types.InlineKeyboardButton(
                text=get_text("links.open_button", "➡️ Открыть"),
                url=btn["url"],
                style="primary"
            )
        ]])
        await callback.message.answer(get_text("links.direct_ready"), reply_markup=kb)
        await callback.answer()
        return

    # type == "generated"
    sm = get_start_message()
    duration = (sm["link_duration_minutes"] if sm else None) or 30

    try:
        invite_url = await create_invite_link(callback.bot, btn["chat_id"], duration)
    except Exception as e:
        await callback.answer(get_text("links.link_error", error=str(e)), show_alert=True)
        return

    kb = types.InlineKeyboardMarkup(inline_keyboard=[[
        types.InlineKeyboardButton(
            text=get_text("links.join_button", "🎟️ Вступить"),
            url=invite_url,
            style="success"
        )
    ]])
    await callback.message.answer(get_text("links.generated_ready", minutes=duration), reply_markup=kb)
    await callback.answer()

# Автоматическое одобрение заявок на вступление намеренно убрано.
# Бот только создаёт пригласительную ссылку-заявку; принять или
# отклонить заявку решает сам администратор чата/канала в Telegram.
