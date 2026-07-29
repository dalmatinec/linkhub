import time
from datetime import datetime, timedelta


async def create_invite_link(bot, chat_id: str, duration_minutes: int) -> str:
    """
    Создаёт пригласительную ссылку-ЗАЯВКУ (creates_join_request=True).
    Бот НЕ одобряет заявки автоматически — решение о принятии заявки
    принимает сам администратор Telegram-чата/канала в самом Telegram.
    """
    expire_date = datetime.now() + timedelta(minutes=duration_minutes)
    link = await bot.create_chat_invite_link(
        chat_id=chat_id,
        creates_join_request=True,
        expire_date=expire_date,
        name=f"req-{int(time.time())}"
    )
    return link.invite_link
