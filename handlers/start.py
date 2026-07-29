import random

from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import FSInputFile

from database import add_user, is_verified, get_start_message
from reply_kb import main_reply_kb
from inline_kb import links_inline_kb
from captcha_states import CaptchaStates
from texts import get_text

router = Router()


async def send_main_menu(message: types.Message):
    """Стартовое сообщение — основная карточка бота: текст + изображение,
    и сразу под ним все созданные администратором inline-кнопки.
    Эта же функция вызывается и при /start, и при нажатии
    «🔗 Актуальные ссылки» — оба раза бот заново отправляет именно её."""
    sm = get_start_message()
    text = sm["text"] if sm and sm["text"] else "Добро пожаловать!"
    if sm and sm["icon_custom_emoji_id"]:
        text = f"<tg-emoji emoji-id=\"{sm['icon_custom_emoji_id']}\">✨</tg-emoji> {text}"

    kb = links_inline_kb()

    if sm and sm["photo_file_id"]:
        await message.answer_photo(sm["photo_file_id"], caption=text, reply_markup=kb)
    else:
        await message.answer(text, reply_markup=kb)


@router.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    if message.chat.type != "private":
        return

    user = message.from_user
    add_user(user.id, user.username, user.first_name)

    if is_verified(user.id):
        await state.clear()
        await send_main_menu(message)
        return

    a, b = random.randint(1, 9), random.randint(1, 9)
    await state.update_data(captcha_a=a, captcha_b=b)
    await state.set_state(CaptchaStates.waiting_answer)
    await message.answer(get_text("captcha.question", a=a, b=b))
