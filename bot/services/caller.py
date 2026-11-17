"""Зазывала: бот отмечает людей пачками по 5 в одном сообщении с текстом, который задал админ.
Например, когда в чат пришла игра. Бот видит только тех, кто писал при нём: онлайн-статус Telegram ботам не даёт."""

import asyncio
import logging
import random
import time

from aiogram import Bot
from aiogram.types import Message

from bot import db, presets
from bot.services.out import say, thread_of
from bot.textutil import esc

log = logging.getLogger(__name__)

PAUSE = 3.5             # секунд между сообщениями, чтобы Telegram не ограничил бота
EMOJIS = ["🎮", "🔥", "⚡", "🎯", "💥", "🎲", "🚀", "👾", "🕹", "⭐"]

_running: dict[int, asyncio.Task] = {}


def running(chat_id: int) -> bool:
    task = _running.get(chat_id)
    return bool(task and not task.done())


async def targets(chat, me_id: int, exclude: int = 0) -> list[tuple[int, str]]:
    chat_id, who, limit = chat["chat_id"], chat["call_who"], chat["call_max"] or 50
    if who == "list":
        rows = [(r["user_id"], r["name"]) for r in await db.call_list(chat_id)]
    else:
        since = {"hour": 3600, "day": 86400, "week": 7 * 86400}.get(who)
        users = await db.users_since(chat_id, time.time() - since if since else 0, limit + 5)
        rows = [(u["user_id"], u["name"]) for u in users]
    from bot.services import guardlink
    blocked = await guardlink.blocked_ids(chat_id)   # замученных и забаненных модератором не зовём
    return [(uid, name) for uid, name in rows if uid not in (me_id, exclude) and uid not in blocked][:limit]


def batch_html(text_html: str, people: list[tuple[int, str]], style: str) -> str:
    if style == "emoji":
        marks = " ".join(f'<a href="tg://user?id={uid}">{EMOJIS[i % len(EMOJIS)]}</a>' for i, (uid, _) in enumerate(people))
    else:
        marks = ", ".join(f'<a href="tg://user?id={uid}">{esc(name or "друг")}</a>' for uid, name in people)
    return f"{text_html}\n\n{marks}"


async def start(bot: Bot, chat, message: Message | None = None, starter: int = 0) -> int:
    """Запускает зазывалу. Возвращает, скольких позовёт (0: некого или уже идёт)."""
    chat_id = chat["chat_id"]
    if running(chat_id):
        return -1
    people = await targets(chat, bot.id, starter)
    if not people:
        return 0
    random.shuffle(people)
    text_html = chat["call_text"] or esc(presets.CALL_DEFAULT_TEXT)
    # если админ ответил командой на пост с игрой, зовём в ответ на этот пост
    anchor = message.reply_to_message if message and message.reply_to_message else None
    thread = thread_of(message)
    task = asyncio.create_task(_run(bot, chat_id, text_html, people, chat["call_style"], anchor, thread))
    _running[chat_id] = task
    task.add_done_callback(lambda _: _running.pop(chat_id, None))
    return len(people)


async def _run(bot: Bot, chat_id: int, text_html: str, people, style: str, anchor, thread) -> None:
    step = presets.CALL_BATCH
    for i in range(0, len(people), step):
        try:
            await say(bot, chat_id, batch_html(text_html, people[i:i + step], style), reply_to=anchor, thread=thread)
        except Exception as exc:
            log.warning("Зазывала в чате %s остановилась: %s", chat_id, exc)
            return
        await asyncio.sleep(PAUSE)


def stop(chat_id: int) -> bool:
    task = _running.pop(chat_id, None)
    if task and not task.done():
        task.cancel()
        return True
    return False
