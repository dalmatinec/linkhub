from aiogram.fsm.state import State, StatesGroup


class AdminLinkStates(StatesGroup):
    waiting_title = State()
    waiting_type = State()
    waiting_direct_url = State()
    waiting_source = State()  # публичная ссылка / Chat ID / пересланное сообщение — бот сам определяет
    waiting_style = State()
    waiting_emoji = State()

    waiting_edit_field_choice = State()
    waiting_edit_title = State()
    waiting_edit_url = State()
    waiting_edit_style = State()
    waiting_edit_emoji = State()

    waiting_delete_confirm = State()


class AdminStartStates(StatesGroup):
    waiting_text = State()
    waiting_photo = State()
    waiting_emoji = State()
    waiting_duration = State()


class AdminBroadcastStates(StatesGroup):
    waiting_forward = State()
    waiting_confirm = State()


class AdminUserStates(StatesGroup):
    waiting_add_id = State()
    waiting_remove_id = State()
