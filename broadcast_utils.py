import asyncio
import time
from database import get_all_users, add_broadcast_record

DELAY_SECONDS = 0.7


async def run_broadcast(bot, from_chat_id: int, message_id: int) -> dict:
    """Копирует сообщение всем пользователям из БД с задержкой 0.7с между отправками.
    Ошибка у одного пользователя не прерывает рассылку."""
    users = get_all_users()
    total = len(users)
    sent = 0
    failed = 0
    start = time.monotonic()

    for user in users:
        try:
            await bot.copy_message(
                chat_id=user["telegram_id"],
                from_chat_id=from_chat_id,
                message_id=message_id
            )
            sent += 1
        except Exception:
            failed += 1
        await asyncio.sleep(DELAY_SECONDS)

    duration_seconds = int(time.monotonic() - start)
    add_broadcast_record(total, sent, failed, duration_seconds)

    return {
        "total": total,
        "sent": sent,
        "failed": failed,
        "duration_seconds": duration_seconds,
    }


def format_duration(seconds: int) -> str:
    minutes = seconds // 60
    secs = seconds % 60
    if minutes:
        return f"{minutes} мин {secs} сек"
    return f"{secs} сек"
