"""Что бот делает сам по расписанию: «чат, как вам пара?», итоги дня вечером,
поздравления с днём рождения. Проверка раз в минуту."""

import asyncio
import logging
import random
import time
from datetime import datetime

from aiogram import Bot
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from bot import ai, config, db, games, nominations, prompts
from bot.services import approval, license, stars, talk
from bot.services.fun import funny_line, nominees_html, rude_line
from bot.services.out import say
from bot.textutil import MSGS, REACTS, esc, human_date, mention, plural

log = logging.getLogger(__name__)

CHECK_EVERY = 60
POLL_HOURS = (13, 21)       # когда бот может спросить «как вам пара»
POLL_CHANCE = 1 / 120       # шанс в каждую минуту, когда чат живой
POLL_ACTIVE_MSGS = 15       # «живой» чат: столько сообщений за последний час
POLL_DURATION = 3600        # голосование длится час
RESULTS_MIN_MSGS = 20       # тихий день без итогов
MANUAL_MIN_MSGS = 5         # итоги по команде можно и при малом числе сообщений
MANUAL_RESULTS_EVERY = 3600 # обычным участникам «итоги» не чаще раза в час на чат
BDAY_HOUR = 10

DAY_WORDS = [
    "сегодня чат ни разу не обсудил ничего полезного. стабильность, уважаю",
    "день прошёл, а смысла в переписке так и не появилось. до завтра",
    "сегодня вы были невыносимы. завтра повторим",
]
BDAY_TEMPLATES = [
    "{name}, с днюхой! пусть всё будет чётко, а чат перестанет тебя бесить. чат, поздравляем!",
    "сегодня день рождения у {name}! расти большим, не будь лапшой. чат, накидайте поздравлений",
]


def midnight_ts() -> float:
    now = datetime.now(config.TZ)
    return now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()


# ---------- «как вам пара» ----------

def poll_markup(poll_id: int, yes: int, no: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=f"💘 Огонь · {yes}", callback_data=f"pp:{poll_id}:1"),
        InlineKeyboardButton(text=f"🙅 Не верю · {no}", callback_data=f"pp:{poll_id}:0"),
    ]])


async def start_pair_poll(bot: Bot, chat) -> bool:
    chat_id = chat["chat_id"]
    since = midnight_ts()
    pair = await db.top_reply_pair(chat_id, since, bot.id)
    if pair and pair[2] >= 3:
        a, b, n = pair
        hook = f"они сегодня {n} раз ответили друг другу и делают вид, что это случайно 👀"
    else:
        pool = [r["user_id"] for r in await db.daily_stats(chat_id, db.today()) if r["msgs"] >= 3]
        picked = games.pick_couple(pool)
        if not picked:
            return False
        a, b = picked
        hook = "не знаю почему, просто чувствую 👀"
    users = {u["user_id"]: u["name"] for u in await db.users_by_ids(chat_id, [a, b])}
    name_a, name_b = users.get(a, "кто-то"), users.get(b, "кто-то")
    poll_id = await db.create_poll(chat_id, a, b, name_a, name_b)
    sent = await say(bot, chat_id,
                     f"💘 <b>Чат, как вам пара?</b>\n\n{mention(a, name_a)} + {mention(b, name_b)}\n\n{hook}",
                     markup=poll_markup(poll_id, 0, 0))
    await db.set_poll_message(poll_id, sent.message_id)
    await talk.remember_self(bot, chat, sent, f"чат, как вам пара: {name_a} + {name_b}?")
    return True


async def on_pair_vote(cb: CallbackQuery) -> None:
    try:
        _, poll_id, vote = cb.data.split(":")
        poll_id, vote = int(poll_id), int(vote)
    except ValueError:
        return await cb.answer()
    poll = await db.get_poll(poll_id)
    if not poll or poll["closed"]:
        return await cb.answer("голосование уже закрыто")
    await db.vote_poll(poll_id, cb.from_user.id, vote)
    yes, no = await db.poll_counts(poll_id)
    try:
        await cb.message.edit_reply_markup(reply_markup=poll_markup(poll_id, yes, no))
    except Exception:
        pass
    await cb.answer("💘 голос учтён" if vote else "🙅 голос учтён")


async def close_polls(bot: Bot) -> None:
    for poll in await db.polls_to_close(time.time() - POLL_DURATION):
        await db.close_poll(poll["id"])
        yes, no = await db.poll_counts(poll["id"])
        a, b = mention(poll["user1"], poll["name1"]), mention(poll["user2"], poll["name2"])
        if yes + no == 0:
            verdict = "никто не проголосовал. чат, вам что, всё равно на любовь?"
        elif yes > no:
            verdict = random.choice([f"чат одобряет. {a}, {b}, готовьте свадьбу, я свидетель 💍",
                                     f"народ сказал своё слово: {a} и {b} теперь официально пара дня 💘"])
        elif no > yes:
            verdict = random.choice([f"чат не верит. {a} и {b}, расходимся, это была ошибка 💔",
                                     f"не судьба. {a}, {b}, остаёмся друзьями 🤝"])
        else:
            verdict = "ничья. чат в замешательстве, как и я"
        try:
            await bot.edit_message_reply_markup(chat_id=poll["chat_id"], message_id=poll["message_id"],
                                                reply_markup=None)
        except Exception:
            pass
        try:
            await say(bot, poll["chat_id"], f"🗳 <b>Голосование закрыто</b>\n💘 {yes} против 🙅 {no}\n\n{verdict}")
        except Exception as exc:
            log.warning("Итог пары не отправился в %s: %s", poll["chat_id"], exc)


# ---------- итоги дня ----------

async def build_results(bot: Bot, chat, manual: bool = False) -> dict | None:
    """Собирает итоги дня: текст (как раньше), подпись для альбома и данные для двух карточек.
    None, если сообщений слишком мало. manual: вызвали посреди дня, хватит и 5 сообщений."""
    chat_id, day = chat["chat_id"], db.today()
    since = midnight_ts()
    people = nominations.people_from_daily(await db.daily_stats(chat_id, day), await db.reacts_by_user(chat_id, since))
    nom = nominations.nominate(people, min_msgs=10)
    if nom.total < (MANUAL_MIN_MSGS if manual else RESULTS_MIN_MSGS):
        return None

    couple = await db.get_couple(chat_id, day)
    if couple is None:
        from bot.services import guardlink
        blocked = await guardlink.blocked_ids(chat_id)   # кого убрала модерация, в пару не берём
        picked = games.pick_couple([p.user_id for p in people if p.msgs > 0 and p.user_id not in blocked])
        if picked:
            await db.set_couple(chat_id, day, *picked)
            couple = await db.get_couple(chat_id, day)
    top_msg = await db.top_reacted(chat_id, since)

    stats = "\n".join(f"{p.name}: {p.msgs} сообщ., мат {p.mat_pct}%" for p in
                      sorted(people, key=lambda p: -p.msgs)[:15])
    rows = await db.history_since(chat_id, since, limit=600)
    system, _ = await talk.context(chat)
    data = await ai.chat_json_as("results", [{"role": "system", "content": system},
                               {"role": "user", "content": prompts.day_task(prompts.transcript(rows, 250, 120),
                                                                            stats)}], max_tokens=400)

    now = datetime.now(config.TZ)
    date = human_date(now.strftime("%m-%d"))
    title = f"📊 <b>Итоги дня на {now:%H:%M}</b>" if manual else "🌙 <b>Итоги дня</b>"
    lines = [title,
             f"{date} · {nom.total} {plural(nom.total, MSGS)} · {nom.people} чел.", ""]
    lines += [line.replace("<b>Болтун:</b>", "<b>Болтун дня:</b>") for line in nominees_html(nom)]
    couple_names = None
    if couple:
        users = {u["user_id"]: u["name"] for u in await db.users_by_ids(chat_id, [couple["user1"], couple["user2"]])}
        couple_names = (users.get(couple["user1"], "кто-то"), users.get(couple["user2"], "кто-то"))
        lines.insert(4, f"💞 <b>Пара дня:</b> {mention(couple['user1'], couple_names[0])} + "
                        f"{mention(couple['user2'], couple_names[1])}")
    rude = rude_line(data)
    if rude:
        lines.append(rude)
    from bot.services import guardlink
    guard_line = guardlink.summary_line(await guardlink.day_counts(chat_id, since))
    if guard_line:
        lines.append(guard_line)
    quote = []
    if top_msg:
        quote = ["", f"🔥 <b>Сообщение дня</b> · {top_msg['total']} {plural(top_msg['total'], REACTS)}",
                 f"<blockquote>{mention(top_msg['user_id'], top_msg['name'])}\n{esc(top_msg['text'][:300])}"
                 "</blockquote>"]
        lines += quote
    word = prompts.clean_reply(str((data or {}).get("joke") or ""), chat["bot_name"]) or random.choice(DAY_WORDS)
    tail = ["", f"🕷 <b>{esc(chat['bot_name'])} о сегодняшнем дне</b>", esc(word)]
    lines += tail

    # подпись под альбомом: коротко, остальное на карточках (лимит подписи 1024 символа)
    caption = "\n".join([title, *([rude] if rude else []), *([guard_line] if guard_line else []), *quote, *tail])
    if len(caption) > 1000:
        caption = "\n".join([title, *tail])[:1000]

    from bot.cards.results import Crew, DayData, Nomination
    noms = []
    if nom.talker:
        noms.append(Nomination("talk", "Болтун дня", nom.talker.user_id, nom.talker.name,
                               f"{nom.talker.msgs} {plural(nom.talker.msgs, MSGS)}"))
    if nom.funny:
        noms.append(Nomination("laugh", "Самый смешной", nom.funny.user_id, nom.funny.name, funny_line(nom.funny)))
    if nom.swearer:
        noms.append(Nomination("swear", "Матершинник", nom.swearer.user_id, nom.swearer.name,
                               f"{nom.swearer.mat_pct}% сообщений с матом"))
    if top_msg:
        noms.append(Nomination("fire", "Сообщение дня", top_msg["user_id"], top_msg["name"],
                               f"сообщение собрало {top_msg['total']} {plural(top_msg['total'], REACTS)}"))
    if couple_names:
        noms.append(Nomination("hearts", "Пара дня", couple["user1"], " + ".join(couple_names), "по версии чата и бота"))
    rude_name = str((data or {}).get("rude") or "").strip()
    if rude_name and len(noms) < 5:   # самого грубого выбирает нейросеть по переписке
        rid = next((p.user_id for p in people if p.name.lower() == rude_name.lower()), 0)
        noms.append(Nomination("angry", "Самый грубый", rid, rude_name,
                               str((data or {}).get("rude_why") or "по мнению бота").strip()[:60]))
    listed = {n.user_id for n in noms}
    quiet = [p for p in people if 0 < p.msgs and p.user_id not in listed]
    if len(noms) < 4 and quiet:       # чтобы карточка не была пустой: тихоня дня
        q = min(quiet, key=lambda p: p.msgs)
        noms.append(Nomination("shush", "Тихоня дня", q.user_id, q.name,
                               f"всего {q.msgs} {plural(q.msgs, MSGS)}, но мы видим"))
    hours: dict[int, int] = {}
    for r in rows:
        if not r["is_bot"]:
            h = datetime.fromtimestamp(r["ts"], config.TZ).hour
            hours[h] = hours.get(h, 0) + 1
    peak = f"{max(hours, key=hours.get):02d}:00" if hours else "-"
    crew = sorted((p for p in people if p.msgs), key=lambda p: -p.msgs)[:5]
    star = max(people, key=lambda p: p.msgs + 3 * p.funny) if people else None
    star_text = ""
    if star:
        star_text = f"{star.name} · {star.msgs} {plural(star.msgs, MSGS)}" + (
            f", {funny_line(star)}" if star.funny else "")
    from bot.cards.results import style_for
    weekday = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"][now.weekday()]
    card = DayData(chat["title"] or "наш чат", f"{date} · {weekday}", nom.total, nom.people, peak, noms,
                   [Crew(p.user_id, p.name, p.msgs) for p in crew], star_text, chat["bot_name"], config.SITE_URL,
                   style_for(chat["chat_id"], chat["card_style"]))
    return {"text": "\n".join(lines), "caption": caption, "card": card, "word": word}


async def _avatar(bot: Bot, user_id: int) -> bytes | None:
    """Маленькая аватарка из профиля Telegram (если человек её не скрыл)."""
    key = (user_id, db.today())
    if key in _AVATARS:
        return _AVATARS[key]
    data = None
    try:
        photos = await bot.get_user_profile_photos(user_id, limit=1)
        if photos.total_count:
            sizes = photos.photos[0]
            small = next((s for s in sizes if s.width >= 160), sizes[-1])
            buf = await bot.download(small.file_id)
            data = buf.read() if buf else None
    except Exception as exc:
        log.info("Аватарку %s не взял: %s", user_id, exc)
    if len(_AVATARS) > 500:
        _AVATARS.clear()
    _AVATARS[key] = data
    return data


_AVATARS: dict[tuple[int, str], bytes | None] = {}


async def render_cards(bot: Bot, card) -> list[bytes]:
    """Две картинки итогов. Пустой список, если Pillow нет или что-то пошло не так (тогда итоги текстом)."""
    from bot.cards import results
    if results.Image is None:
        return []
    ids = {n.user_id for n in card.noms} | {c.user_id for c in card.top}
    avatars = {uid: await _avatar(bot, uid) for uid in ids}
    bot_photo = None
    try:
        bot_photo = (config.ROOT / "bot" / "assets" / "start.jpg").read_bytes()
    except OSError:
        pass
    try:
        first = await asyncio.to_thread(results.logbook, card, avatars, bot_photo)
        second = await asyncio.to_thread(results.crew, card, avatars, bot_photo)
    except Exception:
        log.exception("Карточки итогов не нарисовались")
        return []
    return [x for x in (first, second) if x]


async def send_results(bot: Bot, chat_id: int, built: dict, reply_to=None, prefix: str = "", cards: bool = True):
    """Альбом из двух карточек с подписью; cards=False или не вышло: итоги обычным текстом."""
    from aiogram.types import BufferedInputFile, InputMediaPhoto

    from bot.services.out import reply_params
    images = await render_cards(bot, built["card"]) if cards else []
    if len(images) == 2:
        caption = (prefix + built["caption"])[:1024]
        media = [InputMediaPhoto(media=BufferedInputFile(images[0], "itogi.jpg"), caption=caption, parse_mode="HTML"),
                 InputMediaPhoto(media=BufferedInputFile(images[1], "top.jpg"))]
        try:
            sent = await bot.send_media_group(chat_id, media, reply_parameters=reply_params(reply_to))
            return sent[0] if sent else None
        except Exception as exc:
            log.warning("Альбом итогов не ушёл в %s, шлю текстом: %s", chat_id, exc)
    return await say(bot, chat_id, prefix + built["text"], reply_to=reply_to)


async def post_results(bot: Bot, chat, manual: bool = False, reply_to=None) -> bool:
    """Итоги дня в чат. Вечером по расписанию (час итогов чата, по умолчанию 23:00): две карточки альбомом.
    По команде посреди дня (manual): обычным текстом."""
    built = await build_results(bot, chat, manual)
    if not built:
        return False
    sent = await send_results(bot, chat["chat_id"], built, reply_to=reply_to, cards=not manual)
    if sent:
        await talk.remember_self(bot, chat, sent, f"[итоги дня] {built['word']}")
    return True


async def preview_results(bot: Bot, chat, to_user: int) -> str:
    """Итоги этого чата за сегодня только тебе в личку, в чат ничего не уходит. Возвращает '' или причину."""
    built = await build_results(bot, chat, manual=True)
    if not built:
        return f"сегодня в чате меньше {MANUAL_MIN_MSGS} сообщений, итоги собрать не из чего"
    await send_results(bot, to_user, built,
                       prefix=f"👁 <b>Предпросмотр: {esc(chat['title'] or '')}</b>. В чат не отправлено.\n\n")
    return ""


# ---------- дни рождения ----------

async def greet_birthdays(bot: Bot, chat) -> None:
    now = datetime.now(config.TZ)
    for user in await db.birthdays_today(chat["chat_id"], now.strftime("%m-%d"), now.year):
        await db.mark_bday(chat["chat_id"], user["user_id"], now.year)
        system, _ = await talk.context(chat)
        text = prompts.clean_reply(await ai.chat_as("event", [{"role": "system", "content": system},
                                                  {"role": "user", "content": prompts.bday_task(user["name"],
                                                                                                 user["notes"])}],
                                                 max_tokens=250) or "", chat["bot_name"], limit=700)
        text = text or random.choice(BDAY_TEMPLATES).format(name=user["name"])
        await say(bot, chat["chat_id"],
                  f"🎂 <b>День рождения:</b> {mention(user['user_id'], user['name'])}!\n\n{esc(text)}")


# ---------- планировщик ----------

async def tick(bot: Bot) -> None:
    if license.sleeping():
        await license.tick(bot)
        return
    now = datetime.now(config.TZ)
    day = db.today()
    if now.hour == 4 and now.minute == 30:
        await db.prune_ai_log()   # разбивку расхода держим 40 дней
        from bot.services import guardlink
        await guardlink.cleanup()  # события модератора держим 30 дней
    for chat in await db.list_chats():
        ai.CURRENT_CHAT.set(chat)
        try:
            if chat["results"] and now.hour == chat["results_hour"] and chat["last_results"] != day:
                await db.update_chat(chat["chat_id"], last_results=day)
                await post_results(bot, chat)
            if (chat["pairpoll"] and chat["last_pairpoll"] != day and POLL_HOURS[0] <= now.hour < POLL_HOURS[1]
                    and random.random() < POLL_CHANCE
                    and await db.chat_message_count(chat["chat_id"], time.time() - 3600) >= POLL_ACTIVE_MSGS):
                await db.update_chat(chat["chat_id"], last_pairpoll=day)
                await start_pair_poll(bot, chat)
            if chat["bday"] and now.hour >= BDAY_HOUR:
                await greet_birthdays(bot, chat)
        except Exception:
            log.exception("Плановая задача в чате %s не выполнилась", chat["chat_id"])
    await close_polls(bot)
    from bot.services import backup
    try:
        await backup.tick(bot)
    except Exception:
        log.exception("Бэкап: ошибка в расписании")
    from bot.services import qday
    try:
        await qday.tick(bot)
        await qday.revive_tick(bot)
        from bot.services import plans
        await plans.tick(bot)
    except Exception:
        log.exception("Вопрос дня: ошибка в расписании")
    from bot.economy import hooks as economy
    try:
        await economy.tick(bot)  # голодные питомцы и брошенные кости
    except Exception:
        log.exception("Экономика: ошибка в расписании")
    await stars.expire_titles(bot)
    await stars.refresh_looks()
    await approval.tick(bot)
    await license.tick(bot)
    await license.remind_main(bot)


async def write_public_stats() -> None:
    """Открытые цифры для сайта (сколько чатов и участников). Сайт берёт их из data/stats.json."""
    import json
    reach = await db.reach()
    path = config.DATA_DIR / "stats.json"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"chats": reach["chats"], "members": reach["members"],
                               "updated": int(time.time())}))
    tmp.replace(path)


async def run_scheduler(bot: Bot) -> None:
    while True:
        try:
            # пульс для deploy/health.sh: если файл давно не обновлялся, бот завис, его перезапустят
            (config.DATA_DIR / "heartbeat").write_text(str(int(time.time())))
            await write_public_stats()
            await tick(bot)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Ошибка в ежедневном планировщике")
        await asyncio.sleep(CHECK_EVERY)
