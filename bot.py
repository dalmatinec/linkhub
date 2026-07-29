import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from config import TOKEN
from database import init_db
from auth_middleware import CaptchaMiddleware

from handlers import start, captcha, links, settings
from admin import admin_menu, admin_start, admin_links, admin_broadcast, admin_users, admin_stats, admin_settings


async def main():
    logging.basicConfig(level=logging.INFO)

    init_db()

    bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())

    dp.message.middleware(CaptchaMiddleware())

    # порядок важен: капча -> старт -> настройки/ссылки -> админка
    dp.include_router(captcha.router)
    dp.include_router(start.router)
    dp.include_router(settings.router)
    dp.include_router(links.router)

    dp.include_router(admin_menu.router)
    dp.include_router(admin_start.router)
    dp.include_router(admin_links.router)
    dp.include_router(admin_broadcast.router)
    dp.include_router(admin_users.router)
    dp.include_router(admin_stats.router)
    dp.include_router(admin_settings.router)

    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
