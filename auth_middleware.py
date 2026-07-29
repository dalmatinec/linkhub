from aiogram import BaseMiddleware
from aiogram.types import Message
from database import is_verified
from captcha_states import CaptchaStates


class CaptchaMiddleware(BaseMiddleware):
    async def __call__(self, handler, event: Message, data):
        if isinstance(event, Message) and event.chat.type == "private":
            user_id = event.from_user.id
            current_state = await data["state"].get_state()

            allowed = (
                is_verified(user_id)
                or (event.text and event.text.startswith("/start"))
                or current_state == CaptchaStates.waiting_answer.state
            )

            if not allowed:
                await event.answer("Пожалуйста, отправьте /start, чтобы пройти проверку.")
                return

        return await handler(event, data)
