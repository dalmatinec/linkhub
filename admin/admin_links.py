from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext

from database import (
    is_admin, get_buttons, get_button, add_button, update_button, delete_button, move_button,
    get_all_users,
)
from admin_states import AdminLinkStates
from emoji_utils import extract_custom_emoji_id
from forward_parser import parse_chat_source
from inline_kb import style_choice_kb, cancel_kb
from texts import get_text

router = Router()


def push_prompt_kb():
    t = lambda k: get_text(f"admin.push_prompt.{k}")
    return types.InlineKeyboardMarkup(inline_keyboard=[[
        types.InlineKeyboardButton(text=t("yes"), callback_data="push_yes"),
        types.InlineKeyboardButton(text=t("no"), callback_data="push_no"),
    ]])


async def ask_push_notification(message: types.Message):
    await message.answer(get_text("admin.push_prompt.ask"), reply_markup=push_prompt_kb())


@router.callback_query(F.data == "push_yes")
async def push_yes(callback: types.CallbackQuery):
    text = get_text("admin.push_prompt.notify_text")
    for user in get_all_users(push_only=True):
        try:
            await callback.bot.send_message(user["telegram_id"], text)
        except Exception:
            pass
    await callback.message.answer(get_text("admin.push_prompt.sent"))
    await callback.answer()


@router.callback_query(F.data == "push_no")
async def push_no(callback: types.CallbackQuery):
    await callback.message.answer(get_text("admin.push_prompt.skipped"))
    await callback.answer()

TYPE_ICON = {"direct": "🔗", "generated": "🎟️"}


def links_menu_kb():
    t = lambda k: get_text(f"admin.links_menu.{k}")
    return types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text=t("create"), callback_data="links_create")],
        [types.InlineKeyboardButton(text=t("edit"), callback_data="links_edit")],
        [types.InlineKeyboardButton(text=t("delete"), callback_data="links_delete")],
        [types.InlineKeyboardButton(text=t("reorder"), callback_data="links_reorder")],
        [types.InlineKeyboardButton(text=t("list"), callback_data="links_list")],
        [types.InlineKeyboardButton(text=get_text("admin.menu.back"), callback_data="admin_back_to_menu")],
    ])


def type_choice_kb():
    t = lambda k: get_text(f"admin.links_menu.{k}")
    return types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text=t("type_direct"), callback_data="type_direct")],
        [types.InlineKeyboardButton(text=t("type_generated"), callback_data="type_generated")],
        [types.InlineKeyboardButton(text=get_text("admin.cancel", "❌ Отмена"), callback_data="cancel_links")],
    ])


def emoji_optional_kb():
    return types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text=get_text("admin.links_menu.skip", "Пропустить"), callback_data="emoji_skip")],
        [types.InlineKeyboardButton(text=get_text("admin.cancel", "❌ Отмена"), callback_data="cancel_links")],
    ])


def buttons_pick_kb(prefix: str):
    rows = []
    for b in get_buttons():
        icon = TYPE_ICON.get(b["type"], "")
        rows.append([types.InlineKeyboardButton(text=f"{icon} {b['title']}", callback_data=f"{prefix}_{b['id']}")])
    rows.append([types.InlineKeyboardButton(text=get_text("admin.cancel", "❌ Отмена"), callback_data="cancel_links")])
    return types.InlineKeyboardMarkup(inline_keyboard=rows)


def edit_field_kb(button_id: int):
    t = lambda k: get_text(f"admin.links_menu.{k}")
    return types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text=t("edit_title"), callback_data=f"editfield_title_{button_id}")],
        [types.InlineKeyboardButton(text=t("edit_url"), callback_data=f"editfield_url_{button_id}")],
        [types.InlineKeyboardButton(text=t("edit_color"), callback_data=f"editfield_color_{button_id}")],
        [types.InlineKeyboardButton(text=t("edit_emoji"), callback_data=f"editfield_emoji_{button_id}")],
        [types.InlineKeyboardButton(text=get_text("admin.cancel", "❌ Отмена"), callback_data="cancel_links")],
    ])


def confirm_delete_kb(button_id: int):
    t = lambda k: get_text(f"admin.links_menu.{k}")
    return types.InlineKeyboardMarkup(inline_keyboard=[[
        types.InlineKeyboardButton(text=t("confirm_yes"), callback_data=f"delconfirm_yes_{button_id}"),
        types.InlineKeyboardButton(text=t("confirm_no"), callback_data=f"delconfirm_no_{button_id}"),
    ]])


def reorder_kb():
    rows = []
    buttons = get_buttons()
    for b in buttons:
        icon = TYPE_ICON.get(b["type"], "")
        rows.append([
            types.InlineKeyboardButton(text=get_text("admin.links_menu.move_up", "⬆️"), callback_data=f"reorder_up_{b['id']}"),
            types.InlineKeyboardButton(text=f"{icon} {b['title']}", callback_data="reorder_noop"),
            types.InlineKeyboardButton(text=get_text("admin.links_menu.move_down", "⬇️"), callback_data=f"reorder_down_{b['id']}"),
        ])
    rows.append([types.InlineKeyboardButton(text=get_text("admin.links_menu.reorder_done", "✅ Готово"), callback_data="admin_links")])
    return types.InlineKeyboardMarkup(inline_keyboard=rows)


# ---------- отмена (единая для всех шагов создания/редактирования ссылок) ----------

@router.callback_query(F.data == "cancel_links")
async def cancel_links_flow(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.answer(get_text("admin.cancelled", "✅ Действие отменено."))
    await callback.message.answer(get_text("admin.links_menu.title", "🔗 Управление ссылками"), reply_markup=links_menu_kb())
    await callback.answer()


# ---------- меню ----------

@router.callback_query(F.data == "admin_links")
async def open_links_menu(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer(get_text("admin.not_admin"), show_alert=True)
        return
    await callback.message.edit_text(get_text("admin.links_menu.title", "🔗 Управление ссылками"), reply_markup=links_menu_kb())
    await callback.answer()


@router.callback_query(F.data == "links_list")
async def list_buttons(callback: types.CallbackQuery):
    buttons = get_buttons()
    if not buttons:
        await callback.message.answer(get_text("admin.links_menu.empty_list", "Кнопок пока нет."))
    else:
        lines = [f"{i+1}. {TYPE_ICON.get(b['type'], '')} {b['title']}" for i, b in enumerate(buttons)]
        await callback.message.answer("\n".join(lines))
    await callback.answer()


# ---------- изменение порядка ----------

@router.callback_query(F.data == "links_reorder")
async def reorder_start(callback: types.CallbackQuery):
    buttons = get_buttons()
    if not buttons:
        await callback.message.answer(get_text("admin.links_menu.empty_list", "Кнопок пока нет."))
        await callback.answer()
        return
    await callback.message.answer(get_text("admin.links_menu.reorder_title", "Порядок кнопок (стрелками переместите нужную):"), reply_markup=reorder_kb())
    await callback.answer()


@router.callback_query(F.data.startswith("reorder_up_"))
async def reorder_up(callback: types.CallbackQuery):
    button_id = int(callback.data.replace("reorder_up_", ""))
    move_button(button_id, "up")
    await callback.message.edit_reply_markup(reply_markup=reorder_kb())
    await callback.answer()


@router.callback_query(F.data.startswith("reorder_down_"))
async def reorder_down(callback: types.CallbackQuery):
    button_id = int(callback.data.replace("reorder_down_", ""))
    move_button(button_id, "down")
    await callback.message.edit_reply_markup(reply_markup=reorder_kb())
    await callback.answer()


@router.callback_query(F.data == "reorder_noop")
async def reorder_noop(callback: types.CallbackQuery):
    await callback.answer()


# ---------- создание ----------

@router.callback_query(F.data == "links_create")
async def create_start(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(AdminLinkStates.waiting_title)
    await callback.message.answer(get_text("admin.links_menu.ask_title"), reply_markup=cancel_kb("cancel_links"))
    await callback.answer()


@router.message(AdminLinkStates.waiting_title)
async def create_title(message: types.Message, state: FSMContext):
    await state.update_data(title=message.text.strip())
    await state.set_state(AdminLinkStates.waiting_type)
    await message.answer(get_text("admin.links_menu.ask_type"), reply_markup=type_choice_kb())


@router.callback_query(AdminLinkStates.waiting_type, F.data == "type_direct")
async def create_type_direct(callback: types.CallbackQuery, state: FSMContext):
    await state.update_data(type="direct")
    await state.set_state(AdminLinkStates.waiting_direct_url)
    await callback.message.answer(get_text("admin.links_menu.ask_direct_url"), reply_markup=cancel_kb("cancel_links"))
    await callback.answer()


@router.message(AdminLinkStates.waiting_direct_url)
async def create_direct_url(message: types.Message, state: FSMContext):
    await state.update_data(url=message.text.strip(), chat_id=None)
    await state.set_state(AdminLinkStates.waiting_style)
    await message.answer(get_text("admin.links_menu.ask_style"), reply_markup=style_choice_kb("create_style", "cancel_links"))


@router.callback_query(AdminLinkStates.waiting_type, F.data == "type_generated")
async def create_type_generated(callback: types.CallbackQuery, state: FSMContext):
    await state.update_data(type="generated")
    await state.set_state(AdminLinkStates.waiting_source)
    await callback.message.answer(get_text("admin.links_menu.ask_source_combined"), reply_markup=cancel_kb("cancel_links"))
    await callback.answer()


@router.message(AdminLinkStates.waiting_source)
async def create_source(message: types.Message, state: FSMContext):
    # Администратору не нужно искать ID вручную и не нужно выбирать способ —
    # бот сам определяет, что именно ему прислали: публичную ссылку,
    # Chat ID или пересланное сообщение из приватного/публичного чата.
    chat_id = parse_chat_source(message)
    if not chat_id:
        await message.answer(get_text("admin.links_menu.forward_failed"), reply_markup=cancel_kb("cancel_links"))
        return
    await state.update_data(url=None, chat_id=chat_id)
    await state.set_state(AdminLinkStates.waiting_style)
    await message.answer(get_text("admin.links_menu.ask_style"), reply_markup=style_choice_kb("create_style", "cancel_links"))


@router.callback_query(AdminLinkStates.waiting_style, F.data.startswith("create_style_"))
async def create_style(callback: types.CallbackQuery, state: FSMContext):
    style = callback.data.replace("create_style_", "")
    await state.update_data(style=style)
    await state.set_state(AdminLinkStates.waiting_emoji)
    await callback.message.answer(get_text("admin.links_menu.ask_emoji_optional"), reply_markup=emoji_optional_kb())
    await callback.answer()


@router.callback_query(AdminLinkStates.waiting_emoji, F.data == "emoji_skip")
async def create_emoji_skip(callback: types.CallbackQuery, state: FSMContext):
    await _finalize_creation(callback.message, state, emoji_id=None)
    await callback.answer()


@router.message(AdminLinkStates.waiting_emoji)
async def create_emoji_sent(message: types.Message, state: FSMContext):
    emoji_id = extract_custom_emoji_id(message)
    if not emoji_id:
        await message.answer(get_text("admin.prompts.emoji_not_found"), reply_markup=cancel_kb("cancel_links"))
        return
    await _finalize_creation(message, state, emoji_id=emoji_id)


async def _finalize_creation(message: types.Message, state: FSMContext, emoji_id):
    data = await state.get_data()
    add_button(
        title=data["title"],
        type_=data["type"],
        url=data.get("url"),
        chat_id=data.get("chat_id"),
        style=data.get("style", "primary"),
        icon_custom_emoji_id=emoji_id,
    )
    await state.clear()
    await message.answer(get_text("admin.links_menu.created", title=data["title"]))
    await ask_push_notification(message)


# ---------- редактирование ----------

@router.callback_query(F.data == "links_edit")
async def edit_pick(callback: types.CallbackQuery):
    buttons = get_buttons()
    if not buttons:
        await callback.message.answer(get_text("admin.links_menu.empty_list"))
    else:
        await callback.message.answer(get_text("admin.links_menu.choose_to_edit"), reply_markup=buttons_pick_kb("editsel"))
    await callback.answer()


@router.callback_query(F.data.startswith("editsel_"))
async def edit_choose_field(callback: types.CallbackQuery):
    button_id = int(callback.data.replace("editsel_", ""))
    btn = get_button(button_id)
    if not btn:
        await callback.answer(get_text("links.button_not_found"), show_alert=True)
        return
    await callback.message.answer(get_text("admin.links_menu.edit_what", title=btn["title"]), reply_markup=edit_field_kb(button_id))
    await callback.answer()


@router.callback_query(F.data.startswith("editfield_title_"))
async def edit_title_start(callback: types.CallbackQuery, state: FSMContext):
    button_id = int(callback.data.replace("editfield_title_", ""))
    await state.update_data(edit_button_id=button_id)
    await state.set_state(AdminLinkStates.waiting_edit_title)
    await callback.message.answer(get_text("admin.links_menu.ask_title"), reply_markup=cancel_kb("cancel_links"))
    await callback.answer()


@router.message(AdminLinkStates.waiting_edit_title)
async def edit_title_save(message: types.Message, state: FSMContext):
    data = await state.get_data()
    update_button(data["edit_button_id"], title=message.text.strip())
    await state.clear()
    await message.answer(get_text("admin.links_menu.updated"))


@router.callback_query(F.data.startswith("editfield_url_"))
async def edit_url_start(callback: types.CallbackQuery, state: FSMContext):
    button_id = int(callback.data.replace("editfield_url_", ""))
    await state.update_data(edit_button_id=button_id)
    await state.set_state(AdminLinkStates.waiting_edit_url)
    btn = get_button(button_id)
    prompt = get_text("admin.links_menu.ask_direct_url") if btn["type"] == "direct" else get_text("admin.links_menu.ask_source_combined")
    await callback.message.answer(prompt, reply_markup=cancel_kb("cancel_links"))
    await callback.answer()


@router.message(AdminLinkStates.waiting_edit_url)
async def edit_url_save(message: types.Message, state: FSMContext):
    data = await state.get_data()
    button_id = data["edit_button_id"]
    btn = get_button(button_id)
    if btn["type"] == "direct":
        update_button(button_id, url=message.text.strip())
    else:
        chat_id = parse_chat_source(message)
        if not chat_id:
            await message.answer(get_text("admin.links_menu.forward_failed"), reply_markup=cancel_kb("cancel_links"))
            return
        update_button(button_id, chat_id=chat_id)
    await state.clear()
    await message.answer(get_text("admin.links_menu.updated"))


@router.callback_query(F.data.startswith("editfield_color_"))
async def edit_color_start(callback: types.CallbackQuery, state: FSMContext):
    button_id = int(callback.data.replace("editfield_color_", ""))
    await state.update_data(edit_button_id=button_id)
    await callback.message.answer(get_text("admin.links_menu.ask_style"), reply_markup=style_choice_kb("edit_style", "cancel_links"))
    await callback.answer()


@router.callback_query(F.data.startswith("edit_style_"))
async def edit_color_save(callback: types.CallbackQuery, state: FSMContext):
    style = callback.data.replace("edit_style_", "")
    data = await state.get_data()
    button_id = data.get("edit_button_id")
    if not button_id:
        await callback.answer(get_text("links.button_not_found"), show_alert=True)
        return
    update_button(button_id, style=style)
    await state.clear()
    await callback.message.answer(get_text("admin.links_menu.updated"))
    await callback.answer()


@router.callback_query(F.data.startswith("editfield_emoji_"))
async def edit_emoji_start(callback: types.CallbackQuery, state: FSMContext):
    button_id = int(callback.data.replace("editfield_emoji_", ""))
    await state.update_data(edit_button_id=button_id)
    await state.set_state(AdminLinkStates.waiting_edit_emoji)
    await callback.message.answer(get_text("admin.prompts.send_emoji"), reply_markup=cancel_kb("cancel_links"))
    await callback.answer()


@router.message(AdminLinkStates.waiting_edit_emoji)
async def edit_emoji_save(message: types.Message, state: FSMContext):
    emoji_id = extract_custom_emoji_id(message)
    if not emoji_id:
        await message.answer(get_text("admin.prompts.emoji_not_found"), reply_markup=cancel_kb("cancel_links"))
        return
    data = await state.get_data()
    update_button(data["edit_button_id"], icon_custom_emoji_id=emoji_id)
    await state.clear()
    await message.answer(get_text("admin.links_menu.updated"))


# ---------- удаление ----------

@router.callback_query(F.data == "links_delete")
async def delete_pick(callback: types.CallbackQuery):
    buttons = get_buttons()
    if not buttons:
        await callback.message.answer(get_text("admin.links_menu.empty_list"))
    else:
        await callback.message.answer(get_text("admin.links_menu.choose_to_delete"), reply_markup=buttons_pick_kb("delsel"))
    await callback.answer()


@router.callback_query(F.data.startswith("delsel_"))
async def delete_confirm_ask(callback: types.CallbackQuery):
    button_id = int(callback.data.replace("delsel_", ""))
    btn = get_button(button_id)
    if not btn:
        await callback.answer(get_text("links.button_not_found"), show_alert=True)
        return
    await callback.message.answer(get_text("admin.links_menu.confirm_delete", title=btn["title"]), reply_markup=confirm_delete_kb(button_id))
    await callback.answer()


@router.callback_query(F.data.startswith("delconfirm_yes_"))
async def delete_confirm_yes(callback: types.CallbackQuery):
    button_id = int(callback.data.replace("delconfirm_yes_", ""))
    btn = get_button(button_id)
    title = btn["title"] if btn else ""
    delete_button(button_id)
    await callback.message.answer(get_text("admin.links_menu.deleted", title=title))
    await ask_push_notification(callback.message)
    await callback.answer()


@router.callback_query(F.data.startswith("delconfirm_no_"))
async def delete_confirm_no(callback: types.CallbackQuery):
    await callback.message.answer(get_text("admin.links_menu.confirm_no", "❌ Отмена"))
    await callback.answer()
