"""Обычные сообщения в группе: решаем, отвечать или нет, и чем."""

import logging
import random
import time
from datetime import datetime

from aiogram import Bot, F, Router
from aiogram.types import Message

from bot import brain, config, db, presets
from bot.middlewares import GROUPS, TRACKED, describe
from bot.services import fun, memory, perms, quiz, talk, triggers
from bot.services.out import say

log = logging.getLogger(__name__)
router = Router(name="group")
spam_guard = brain.RateLimit(limit=5, window=60)

QUIET_REPLIES = ["ладно, на час притихну 🤐 позовёте по имени, отвечу",
                 "понял, час почти молчу. но если позовёте, я тут 👀",
                 "окей, сбавляю обороты на часик 😶"]
TALK_REPLIES = ["о, наконец-то, я соскучился 😎", "всё, я снова с вами, держитесь", "ну всё, понеслась 🔥"]


@router.message(F.chat.type.in_(GROUPS), F.content_type.in_(TRACKED))
async def on_message(message: Message, bot: Bot, chat_row=None, user_row=None) -> None:
    if chat_row is None or user_row is None:
        return  # другой бот, канал или аноним-админ: молчим
    chat_id = message.chat.id
    memory.maybe_update(chat_id, user_row)
    from bot.services import guardlink
    if await guardlink.is_blocked(chat_id, user_row["user_id"]):
        return  # замученному или забаненному модератором не отвечаем

    trig = await triggers.find(chat_id, message.text or "")
    if trig:
        try:
            await triggers.send(bot, chat_id, trig, reply_to=message)
        except Exception:
            log.exception("Триггер %s в чате %s не отправился", trig["word"], chat_id)
        return

    me = await bot.me()
    text = message.text or message.caption or ""
    rt = message.reply_to_message
    reply_to_bot = bool(rt and rt.from_user and rt.from_user.id == me.id)
    aliases = brain.parse_aliases(chat_row["bot_name"], chat_row["aliases"])
    addressed = brain.is_addressed(text, me.username or "", aliases, reply_to_bot)

    now = time.time()
    if not addressed:
        hour = datetime.now(config.TZ).hour
        if presets.in_quiet(hour, chat_row["quiet_from"], chat_row["quiet_to"]):
            return  # тихие часы: сам не влезает, но на обращения отвечает
    from bot.services import plans
    chance, ai_share = plans.effective(chat_row)   # потолки владельца: админ чата выше не поставит
    if not addressed and chat_row["quiet_until"] > now:
        chance *= presets.QUIET_FACTOR  # «помолчи»: сам влезает в 10 раз реже, на обращения отвечает как обычно
    creator_hit = False
    if not addressed and config.CREATOR_IDS:
        if user_row["user_id"] in config.CREATOR_IDS:
            chance, creator_hit = max(chance, 0.12), True
        elif await _mentions_creator(message):
            chance, creator_hit = max(chance, 0.3), True
    act = brain.decide(addressed, now, chat_row["last_jump"], chat_row["cooldown"], chance, ai_share)
    if act is brain.Act.PHRASE and (creator_hit or user_row["user_id"] in config.CREATOR_IDS):
        act = brain.Act.AI_JUMP  # про создателя говорит сам, а не фразой из базы
    if act is brain.Act.NONE:
        return
    if act is brain.Act.AI_REPLY and not spam_guard.allow(chat_id, user_row["user_id"], time.time()):
        return  # человек долбит бота обращениями: молча пропускаем, ИИ не тратим

    lock = talk.chat_lock(chat_id)
    if act is not brain.Act.AI_REPLY:
        if lock.locked():
            return  # бот уже что-то пишет в этот чат, второй раз не влезаем
        await db.update_chat(chat_id, last_jump=time.time())

    author = user_row["name"]
    intent = brain.detect_intent(text) if act is brain.Act.AI_REPLY else None
    if intent == "quiz" and not (chat_row["games"] and chat_row["quiz"]):
        intent = None
    if intent in ("quiet", "talk"):
        if not await perms.is_admin(bot, message):
            await say(bot, chat_id, "это пусть админы решают 😏", reply_to=message)
        elif intent == "quiet":
            await db.update_chat(chat_id, quiet_until=now + 3600)
            await say(bot, chat_id, random.choice(QUIET_REPLIES), reply_to=message)
        else:
            await db.update_chat(chat_id, quiet_until=0)
            await say(bot, chat_id, random.choice(TALK_REPLIES), reply_to=message)
        return
    if intent == "summary" and not await perms.is_admin(bot, message):
        await say(bot, chat_id, "сводку делаю только по просьбе админов чата", reply_to=message)
        return
    try:
        async with lock:
            if intent == "summary":
                await fun.summary(bot, chat_row, message, text)
            elif intent == "joke":
                await fun.joke(bot, chat_row, message, author)
            elif intent == "roast":
                await fun.roast(bot, chat_row, message, user_row)
            elif intent == "quiz":
                await quiz.start(bot, chat_row, message)
            elif act is brain.Act.PHRASE:
                await talk.phrase_answer(bot, chat_row, message, author)
            else:
                await talk.ai_answer(bot, chat_row, message, author, text or describe(message),
                                     jump=act is brain.Act.AI_JUMP)
    except Exception:
        log.exception("Не получилось ответить в чате %s", chat_id)



async def _mentions_creator(message: Message) -> bool:
    """Создателя отметили: кликабельным упоминанием по ID или его @юзернеймом (юзернейм уникален, имя нет)."""
    for ent in message.entities or message.caption_entities or []:
        if ent.type == "text_mention" and ent.user and ent.user.id in config.CREATOR_IDS:
            return True
    text = (message.text or message.caption or "").lower()
    if "@" not in text:
        return False
    for uid in config.CREATOR_IDS:
        username = await db.username_of(uid)
        if username and f"@{username.lower()}" in text:
            return True
    return False
