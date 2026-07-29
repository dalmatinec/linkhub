from aiogram import Router, types
from aiogram.fsm.context import FSMContext

from database import set_verified
from captcha_states import CaptchaStates
from texts import get_text
from reply_kb import main_reply_kb
from handlers.start import send_main_menu

router = Router()


@router.message(CaptchaStates.waiting_answer)
async def check_captcha(message: types.Message, state: FSMContext):
    data = await state.get_data()
    correct = data.get("captcha_a", 0) + data.get("captcha_b", 0)

    try:
        answer = int((message.text or "").strip())
    except ValueError:
        answer = None

    if answer == correct:
        set_verified(message.from_user.id)
        await state.clear()
        # Нижняя reply-клавиатура ("🔗 Актуальные ссылки" / "⚙️ Настройки")
        # устанавливается один раз здесь и дальше остаётся у пользователя,
        # поэтому стартовая карточка ниже свободна использовать inline-кнопки.
        await message.answer(get_text("captcha.passed", "✅ Проверка пройдена!"), reply_markup=main_reply_kb())
        await send_main_menu(message)
    else:
        await message.answer(get_text("captcha.wrong", "❌ Неверно, попробуйте ещё раз."))
