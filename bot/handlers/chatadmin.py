"""«⚙️ Мои чаты»: создатели чатов и админы с правом назначать админов сами настраивают бота у себя.
Видят только свои чаты, где бот одобрен. Деньги, реклама, фразы, стикеры и тексты меню только у владельца бота.

Разделы: личность, активность, фишки, правила, триггеры, зазывала, статистика, пробный ответ."""

import time
from datetime import datetime, timedelta

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message, User

from bot import ai, config, db, presets
from bot.presets import CLIENT_TOGGLES, FIELDS, every, pct, quiet_text
from bot.services import caller, menu, talk, triggers
from bot.textutil import esc, full_name, short

router = Router(name="chatadmin")
_rights: dict[tuple[int, int], tuple[float, bool]] = {}

DENIED = "Настраивать бота могут создатель чата и админы с правом назначать админов"
MAX_TRIGGERS = 30
WEEKDAYS = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]


class McEdit(StatesGroup):
    value = State()


class McTry(StatesGroup):
    text = State()


class McTrig(StatesGroup):
    word = State()
    reply = State()


class McCall(StatesGroup):
    add = State()


class McImport(StatesGroup):
    file = State()


class McQday(StatesGroup):
    add = State()


def _kb(rows: list[list[tuple]]) -> InlineKeyboardMarkup:
    out = []
    for row in rows:
        if not row:
            continue
        buttons = []
        for t, d, *s in row:
            style = s[0] if s and s[0] else None
            if d.startswith(("http://", "https://")):
                buttons.append(InlineKeyboardButton(text=t, url=d, style=style))
            else:
                buttons.append(InlineKeyboardButton(text=t, callback_data=d, style=style))
        out.append(buttons)
    return InlineKeyboardMarkup(inline_keyboard=out)


def _opt(label: str, data: str, on: bool) -> tuple[str, str, str]:
    """Кнопка-вариант: выбранная синяя с галочкой."""
    return (f"✓ {label}" if on else label), data, ("primary" if on else "")


async def can_manage(bot: Bot, user_id: int, chat_id: int) -> bool:
    """Владелец бота, создатель чата или админ с правом назначать админов, и бот в чате одобрен.
    Ответ Telegram кэшируем на 2 мин."""
    chat = await db.get_chat(chat_id)
    if not chat or not chat["active"] or not chat["approved"]:
        return False
    if user_id in config.OWNER_IDS:
        return True
    key = (chat_id, user_id)
    hit = _rights.get(key)
    if hit and time.time() - hit[0] < 120:
        return hit[1]
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        ok = member.status == "creator" or (member.status == "administrator"
                                            and bool(getattr(member, "can_promote_members", False)))
    except Exception:
        ok = False
    _rights[key] = (time.time(), ok)
    return ok


async def my_chats(bot: Bot, user_id: int) -> list:
    return [c for c in await db.candidate_chats(user_id) if await can_manage(bot, user_id, c["chat_id"])]


async def has_chats(user: User) -> bool:
    bot = menu.CURRENT_BOT
    return bool(bot and await my_chats(bot, user.id))


menu.SHOW_IF["act:mychats"] = has_chats


async def _show(target: Message | CallbackQuery, text: str, kb: InlineKeyboardMarkup) -> None:
    if isinstance(target, CallbackQuery):
        try:
            await target.answer()
        except Exception:
            pass
        try:
            return await target.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
        except Exception as exc:
            if "not modified" in str(exc):
                return
            target = target.message
    await target.answer(text, parse_mode="HTML", reply_markup=kb)


async def show_list(bot: Bot, target: Message | CallbackQuery) -> None:
    chats = await my_chats(bot, target.from_user.id)
    if not chats and not await db.lost_chats(target.from_user.id):
        me = await bot.me()
        return await _show(target, "⚙️ <b>Мои чаты</b>\n\nЗдесь появятся чаты, где ты создатель или админ с правом "
                                   "назначать админов и где бот уже работает.\n\nПока таких нет. Если только что "
                                   "добавил бота, дождись одобрения: я напишу сюда, когда всё готово.",
                           _kb([[("➕ Добавить бота в чат", f"https://t.me/{me.username}?startgroup=true", "success")],
                                [("⬅️ В меню", "sc:start")]]))
    rows = [[(f"💬 {short(c['title'] or str(c['chat_id']), 40)}", f"mc:o:{c['chat_id']}")] for c in chats]
    if await db.lost_chats(target.from_user.id):
        rows.append([("📦 Перенести из пропавшего чата", "mc:lost")])
    await _show(target, "⚙️ <b>Мои чаты</b>\n\nВыбери чат, чтобы настроить бота в нём.",
                _kb(rows + [[("⬅️ В меню", "sc:start")]]))


@router.callback_query(F.data.in_({"mc:list", "act:mychats"}))
async def cb_list(cb: CallbackQuery, bot: Bot, state: FSMContext) -> None:
    await state.clear()
    await show_list(bot, cb)


async def _guard(cb: CallbackQuery, bot: Bot, chat_id: int) -> bool:
    if await can_manage(bot, cb.from_user.id, chat_id):
        return True
    await cb.answer(DENIED, show_alert=True)
    return False


def last_days(n: int) -> list[str]:
    now = datetime.now(config.TZ)
    return [(now - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(n - 1, -1, -1)]


def status_line(c) -> str:
    from bot.services.approval import until_text
    if c["free"]:
        return "🆓 бесплатная версия: без нейросети, отвечаю заготовками"
    if c["rent_until"]:
        kind = "🎁 пробный до" if c["trial"] else "📅 аренда до"
        return f"🟢 работаю · {kind} {until_text(c['rent_until'])}"
    return "🟢 работаю"


async def card(target, chat_id: int, viewer: int = 0) -> None:
    c = await db.get_chat(chat_id)
    week = sum((await db.days_totals(chat_id, last_days(7))).values())
    lines = [f"⚙️ <b>{esc(c['title'] or str(chat_id))}</b>", status_line(c),
             f"👥 {c['members'] or '?'} участников · 💬 {week} сообщ. за неделю", "",
             f"🎭 <b>{esc(c['bot_name'])}</b>, {esc(short(c['persona'], 70))}",
             f"📌 {esc(short(c['topic'], 70))}",
             f"💬 болтаю: {pct(c['chance'])}" + (f" · 🌙 тихо {quiet_text(c['quiet_from'], c['quiet_to'])}"
                                                if c["quiet_from"] >= 0 else "")]
    if c["quiet_until"] > time.time():
        lines.append(f"🤫 молчу до {datetime.fromtimestamp(c['quiet_until'], config.TZ):%H:%M}")
    cid = chat_id
    rows = [
        [("🎭 Личность", f"mc:s:{cid}:who"), ("💬 Активность", f"mc:s:{cid}:act")],
        [("🎲 Фишки", f"mc:s:{cid}:fx"), ("🛡 Правила", f"mc:s:{cid}:rules")],
        [("📝 Триггеры", f"mc:s:{cid}:trig"), ("📣 Зазывала", f"mc:s:{cid}:call")],
        [("📊 Статистика", f"mc:s:{cid}:stats"), ("🧰 Перенос и экспорт", f"mc:s:{cid}:tools")],
        [("🛡 Модерация", f"mc:g:{cid}")],
        [("💳 Подключить платную" if c["free"] or c["trial"] else "💳 Продлить аренду", f"rt:{cid}", "success"),
         ("🆘 Поддержка", f"mc:sup:{cid}")],
        [("👀 Пробный ответ", f"mc:try:{cid}"), ("🧹 Стереть память", f"mc:w:{cid}")],
        [("⬅️ Мои чаты", "mc:list")] + ([("👑 В админку", f"ch:o:{cid}")] if viewer in config.OWNER_IDS else []),
    ]
    await _show(target, "\n".join(lines), _kb(rows))


LOCKED = "🔒 Частоту, долю ИИ и паузу в этом чате настроил владелец бота"


def _activity(c, owner: bool = False) -> tuple[str, list]:
    """owner: владелец видит все шаги, админы чатов только до потолков из админки владельца."""
    from bot.services import plans
    cid = c["chat_id"]
    cap_chance = 1.0 if owner else plans.chance_cap()
    cap_ai = 1.0 if owner else plans.ai_share_cap()
    results = f"в {c['results_hour']}:00" if c["results"] else "выкл"
    revive = f"через {c['revive']} мин" if c["revive"] else "выкл"
    text = (f"💬 <b>Активность</b>\n\n"
            f"Сам влезаю в разговор: <b>{pct(c['chance'])}</b>\n<i>{every(c['chance'])}</i>\n\n"
            f"🤖 Из них через ИИ: <b>{pct(c['ai_share'])}</b>, остальное фразы и стикеры\n"
            f"⏱ Пауза между влезаниями: <b>{c['cooldown']} сек</b>\n"
            f"🌙 Тихие часы: <b>{quiet_text(c['quiet_from'], c['quiet_to'])}</b>\n"
            f"<i>ночью сам не пишу, но отвечаю, если позвать</i>\n"
            f"🌙 Оживлять тишину: <b>{revive}</b>\n"
            f"<i>днём, если в чате тихо, бот вкинет шутку, вопрос или позовёт на викторину</i>\n"
            f"😏 Юмор: <b>{presets.HUMOR.get(c['humor'], '')}</b>\n"
            f"🕚 Итоги дня: <b>{results}</b>\n\n"
            "<i>Если меня зовут по имени или отвечают мне, отвечаю всегда.</i>")
    steps = [(i, v) for i, v in enumerate(presets.CHANCE_STEPS) if v <= cap_chance + 1e-9]
    rows = [[_opt("выкл" if v == 0 else pct(v), f"mc:v:{cid}:chance:{i}", abs(min(c["chance"], cap_chance) - v) < 1e-6)
             for i, v in steps[k:k + 5]] for k in range(0, len(steps), 5)]
    rows.append([(f"🤖 ИИ: {pct(min(c['ai_share'], cap_ai))}", f"mc:c:{cid}:ai_share"),
                 (f"⏱ Пауза: {c['cooldown']}с", f"mc:c:{cid}:cooldown")])
    rows.append([_opt("🌙 выкл" if a < 0 else f"{a:02d}-{b:02d}", f"mc:v:{cid}:quiet:{i}",
                      (a, b) == (c["quiet_from"], c["quiet_to"])) for i, (a, b) in enumerate(presets.QUIET_OPTIONS)])
    rows.append([_opt("🌙 выкл" if m == 0 else f"{m} мин", f"mc:v:{cid}:rv:{m}", c["revive"] == m)
                 for m in presets.REVIVE_MINUTES])
    rows.append([_opt(label, f"mc:v:{cid}:humor:{k}", c["humor"] == k) for k, label in presets.HUMOR.items()])
    rows.append([_opt(f"{h}:00", f"mc:v:{cid}:rh:{h}", bool(c["results"]) and c["results_hour"] == h)
                 for h in (21, 22, 23)] + [_opt("Выкл", f"mc:v:{cid}:rh:0", not c["results"])])
    return text, rows


async def section(target, chat_id: int, sec: str) -> None:
    c = await db.get_chat(chat_id)
    cid = chat_id
    back = [("⬅️ К чату", f"mc:o:{cid}")]
    if sec == "who":
        text = (f"🎭 <b>Личность</b>\n\n<b>Имя:</b> {esc(c['bot_name'])}\n"
                f"<b>Ещё откликается на:</b> {esc(c['aliases']) or 'нет'}\n\n"
                f"<b>Кто он и характер:</b>\n<blockquote expandable>{esc(short(c['persona'], 2500))}</blockquote>\n"
                f"<b>Тема чата:</b>\n<blockquote>{esc(short(c['topic'], 600))}</blockquote>\n"
                "<i>Характер можно писать длинно и подробно: кто он, где находится, как общается. "
                "Чем подробнее, тем живее бот.</i>")
        rows = [[("✏️ Имя", f"mc:e:{cid}:bot_name"), ("🔤 Доп. имена", f"mc:e:{cid}:aliases")],
                [("🎭 Характер", f"mc:e:{cid}:persona"), ("📌 Тема", f"mc:e:{cid}:topic")],
                [("✨ Готовые характеры", f"wz:s:{cid}")], back]
    elif sec == "act":
        owner = getattr(getattr(target, "from_user", None), "id", 0) in config.OWNER_IDS
        text, rows = _activity(c, owner)
        if c["act_locked"] and not owner:   # закреплено владельцем: показываем значения, без кнопок частоты
            text += f"\n\n{LOCKED}"
            rows = [r for r in rows if not any(":chance:" in b[1] or ":ai_share" in b[1] or ":cooldown" in b[1]
                                               for b in r)]
        if owner:
            rows.insert(0, [(("🔒 Закреплено владельцем" if c["act_locked"] else "🔓 Админы чата могут менять"),
                             f"mc:lock:{cid}")])
        rows.append(back)
    elif sec == "fx":
        text = (f"🎲 <b>Фишки в {esc(c['title'] or '')}</b>\n\nНажми, чтобы включить или выключить.\n\n"
                f"🧠 Вопросов в викторине: <b>{c['quiz_count']}</b>")
        items = list(CLIENT_TOGGLES.items())
        rows = [[(f"{'✅' if c[f] else '❌'} {label}", f"mc:t:{cid}:{f}") for f, label in items[i:i + 2]]
                for i in range(0, len(items), 2)]
        rows.append([_opt(f"🧠 {n} вопросов", f"mc:v:{cid}:qc:{n}", c["quiz_count"] == n) for n in presets.QUIZ_COUNTS])
        rows.append([("❓ Свои вопросы дня", f"mc:s:{cid}:qday")])
        rows.append(back)
    elif sec == "rules":
        text = (f"🛡 <b>Правила</b>\n\n"
                f"🚫 Не шутить про: <i>{esc(c['banned']) or 'ограничений нет'}</i>\n"
                f"🛡 Прожаривать админов: <i>{'нельзя' if c['protect_admins'] else 'можно'}</i>\n"
                f"🤬 Мат: <i>{presets.MAT.get(c['mat'], '')}</i>")
        rows = [[("🚫 Запретные темы", f"mc:e:{cid}:banned")],
                [(f"🛡 Защита админов: {'✅' if c['protect_admins'] else '❌'}", f"mc:t:{cid}:protect_admins")],
                [_opt(label, f"mc:v:{cid}:mat:{k}", c["mat"] == k) for k, label in presets.MAT.items()], back]
    elif sec == "trig":
        items = await db.list_triggers(cid)
        listing = "\n".join(f"• <code>{esc(t['word'])}</code> → {_trig_kind(t)}" for t in items) or "пока нет"
        text = (f"📝 <b>Триггеры</b> ({len(items)})\nСлово в чате, на которое я сразу отвечаю твоим текстом, "
                f"фото или видео. Удобно для правил, прайса, адреса.\n\n{listing}")
        rows = [[(short(t["word"], 18), f"mc:td:{t['id']}") for t in items[i:i + 3]] for i in range(0, len(items), 3)]
        rows += [[("➕ Новый триггер", f"mc:tn:{cid}", "success")], back]
    elif sec == "call":
        people = len(await db.call_list(cid))
        sample = c["call_text"] or esc(presets.CALL_DEFAULT_TEXT)
        style = "имена спрятаны в эмодзи" if c["call_style"] == "emoji" else "именами"
        text = (f"📣 <b>Зазывала</b>\nОтмечаю людей пачками по {presets.CALL_BATCH} в сообщении, например когда "
                f"в чат пришла игра.\n\n<b>Текст:</b>\n<blockquote>{sample}</blockquote>\n"
                f"<b>Кого звать:</b> {presets.CALL_WHO.get(c['call_who'], '')}\n"
                f"<b>Как отмечать:</b> {style}\n<b>Максимум:</b> {c['call_max']} человек\n\n"
                "Запуск в чате: /call или слово <b>зазывай</b>, можно ответом на пост с игрой. Стоп: /stopcall\n"
                "<i>Онлайн Telegram ботам не показывает, поэтому ближе всего к онлайну вариант писали за час. "
                "Зову только тех, кто писал, пока я в чате.</i>")
        who = list(presets.CALL_WHO.items())
        rows = [[("✏️ Текст", f"mc:e:{cid}:call_text")]]
        rows += [[_opt(label, f"mc:v:{cid}:cw:{k}", c["call_who"] == k) for k, label in who[i:i + 2]]
                 for i in range(0, len(who), 2)]
        rows.append([_opt(label, f"mc:v:{cid}:cs:{k}", c["call_style"] == k)
                     for k, label in (("names", "👤 Именами"), ("emoji", "🎮 В эмодзи"))])
        rows.append([_opt(str(n), f"mc:v:{cid}:cm:{n}", c["call_max"] == n) for n in presets.CALL_MAX])
        rows += [[(f"📋 Мой список ({people})", f"mc:cl:{cid}")],
                 [("▶️ Позвать сейчас", f"mc:run:{cid}", "success")], back]
    elif sec == "qday":
        from bot.services.qday import HOUR
        queue = [q for q in (c["qday_queue"] or "").splitlines() if q.strip()]
        listing = "\n".join(f"{i + 1}. {esc(short(q, 120))}" for i, q in enumerate(queue[:15])) or "пусто"
        text = (f"❓ <b>Вопрос дня</b>: {'✅ включён' if c['qday'] else '❌ выключен'}, каждый день в {HOUR}:00\n\n"
                "Если очередь пуста, вопрос придумывает бот под тему чата. Свои вопросы идут первыми, "
                f"по одному в день.\n\n<b>Очередь ({len(queue)}):</b>\n{listing}")
        rows = [[("✏️ Добавить свои вопросы", f"mc:qa:{cid}", "success")],
                [("▶️ Задать сейчас", f"mc:qn:{cid}"), ("🗑 Очистить", f"mc:qx:{cid}")],
                [(f"{'✅' if c['qday'] else '❌'} Вопрос дня", f"mc:t:{cid}:qday")],
                [("⬅️ Фишки", f"mc:s:{cid}:fx")]]
    elif sec == "tools":
        text = ("🧰 <b>Перенос и экспорт</b>\n\n"
                "📦 <b>Перенести в другой чат</b>: если этот чат пропал, забанили или вы переехали в новую группу. "
                "Переносится всё: характер и настройки, память о людях и дни рождения, репутация, топ викторины, "
                "триггеры, список зазывалы, одобрение и остаток аренды.\n\n"
                "📤 <b>Скачать настройки</b> файлом и 📥 <b>загрузить</b> их в любой чат: характер, тема, частота, "
                "фишки, правила, зазывала и триггеры.")
        rows = [[("📦 Перенести в другой чат", f"mc:mv:{cid}", "primary")],
                [("📤 Скачать настройки", f"mc:ex:{cid}"), ("📥 Загрузить", f"mc:im:{cid}")], back]
    else:  # stats
        days = last_days(7)
        totals = await db.days_totals(cid, days)
        top = await db.top_talkers(cid, days, 5)
        peak = max(totals.values()) or 1
        bars = []
        for d, n in totals.items():
            wd = WEEKDAYS[datetime.strptime(d, "%Y-%m-%d").weekday()]
            bar = "▇" * (max(1, round(n * 8 / peak)) if n else 0)
            bars.append(f"<code>{wd} {bar:<8} {n}</code>")
        medals = ["🥇", "🥈", "🥉", "4.", "5."]
        talkers = "\n".join(f"{medals[i]} {esc(r['name'])}: {r['msgs']}" for i, r in enumerate(top)) or "пока пусто"
        text = (f"📊 <b>Статистика за 7 дней</b>\n\n💬 Сообщений: <b>{sum(totals.values())}</b>\n"
                f"👥 Участников: <b>{c['members'] or '?'}</b> · знаю в лицо: <b>{await db.known_people(cid)}</b>\n\n"
                + "\n".join(bars) + f"\n\n🗣 <b>Самые активные:</b>\n{talkers}")
        rows = [back]
    await _show(target, text, _kb(rows))


def _trig_kind(t) -> str:
    return {"photo": "фото", "video": "видео", "gif": "гифка", "sticker": "стикер"}.get(t["media_kind"], "текст")


@router.callback_query(F.data.startswith("mc:sup:"))
async def cb_support(cb: CallbackQuery, bot: Bot, state: FSMContext) -> None:
    """Админ чата пишет владельцу бота. Ответ придёт через обычную поддержку."""
    from bot.handlers.private import SupportWrite
    chat = await db.get_chat(int(cb.data.split(":")[2]))
    await state.set_state(SupportWrite.message)
    await state.update_data(topic=f"чат {chat['title']}" if chat else "чат")
    await menu.show(bot, cb, "support")


@router.callback_query(F.data.startswith("mc:o:"))
async def cb_open(cb: CallbackQuery, bot: Bot, state: FSMContext) -> None:
    await state.clear()
    cid = int(cb.data.split(":")[2])
    if await _guard(cb, bot, cid):
        await card(cb, cid, cb.from_user.id)


@router.callback_query(F.data.startswith("mc:s:"))
async def cb_section(cb: CallbackQuery, bot: Bot, state: FSMContext) -> None:
    await state.clear()
    _, _, cid, sec = cb.data.split(":")
    if await _guard(cb, bot, int(cid)):
        await section(cb, int(cid), sec)


CYCLES = {"ai_share": presets.AI_SHARE_STEPS, "cooldown": presets.COOLDOWN_STEPS}


@router.callback_query(F.data.startswith("mc:lock:"))
async def cb_lock(cb: CallbackQuery) -> None:
    """Только владелец: закрепить настройки активности чата, чтобы админы чата их не меняли."""
    if cb.from_user.id not in config.OWNER_IDS:
        return await cb.answer()
    cid = int(cb.data.split(":")[2])
    chat = await db.get_chat(cid)
    await db.update_chat(cid, act_locked=0 if chat["act_locked"] else 1)
    await cb.answer("🔒 Закреплено: админы чата не поменяют" if not chat["act_locked"] else "🔓 Админы снова могут менять")
    await section(cb, cid, "act")
TOGGLE_FIELDS = set(CLIENT_TOGGLES) | {"protect_admins"}


@router.callback_query(F.data.startswith(("mc:c:", "mc:t:")))
async def cb_change(cb: CallbackQuery, bot: Bot) -> None:
    _, op, cid, field = cb.data.split(":")
    cid = int(cid)
    if not await _guard(cb, bot, cid):
        return
    chat = await db.get_chat(cid)
    if op == "c" and field in CYCLES and chat["act_locked"] and cb.from_user.id not in config.OWNER_IDS:
        return await cb.answer(LOCKED, show_alert=True)
    if op == "c" and field in CYCLES:
        steps = CYCLES[field]
        if field == "ai_share" and cb.from_user.id not in config.OWNER_IDS:
            from bot.services import plans
            steps = [v for v in steps if v <= plans.ai_share_cap() + 1e-9]
        await db.update_chat(cid, **{field: presets.next_value(steps, chat[field])})
        return await section(cb, cid, "act")
    if op == "t" and field in TOGGLE_FIELDS:
        await db.update_chat(cid, **{field: 0 if chat[field] else 1})
    await section(cb, cid, "rules" if field == "protect_admins" else "fx")


@router.callback_query(F.data.startswith("mc:v:"))
async def cb_value(cb: CallbackQuery, bot: Bot) -> None:
    """Выбор значения кнопкой: шанс, тихие часы, юмор, итоги, мат, зазывала, число вопросов."""
    _, _, cid, key, val = cb.data.split(":")
    cid = int(cid)
    if not await _guard(cb, bot, cid):
        return
    sec = {"mat": "rules", "qc": "fx", "cw": "call", "cs": "call", "cm": "call"}.get(key, "act")
    try:
        if key == "chance" and (await db.get_chat(cid))["act_locked"] and cb.from_user.id not in config.OWNER_IDS:
            return await cb.answer(LOCKED, show_alert=True)
        if key == "chance":
            from bot.services import plans
            value = presets.CHANCE_STEPS[int(val)]
            if cb.from_user.id not in config.OWNER_IDS and value > plans.chance_cap() + 1e-9:
                return await cb.answer(f"максимум {int(plans.chance_cap() * 100)}%", show_alert=True)
            await db.update_chat(cid, chance=value)
        elif key == "quiet":
            a, b = presets.QUIET_OPTIONS[int(val)]
            await db.update_chat(cid, quiet_from=a, quiet_to=b)
        elif key == "rv" and int(val) in presets.REVIVE_MINUTES:
            await db.update_chat(cid, revive=int(val))
        elif key == "humor" and int(val) in presets.HUMOR:
            await db.update_chat(cid, humor=int(val))
        elif key == "rh":
            h = int(val)
            await db.update_chat(cid, **({"results": 0} if h == 0 else {"results": 1, "results_hour": h}))
        elif key == "mat" and int(val) in presets.MAT:
            await db.update_chat(cid, mat=int(val))
        elif key == "qc" and int(val) in presets.QUIZ_COUNTS:
            await db.update_chat(cid, quiz_count=int(val))
        elif key == "cw" and val in presets.CALL_WHO:
            await db.update_chat(cid, call_who=val)
        elif key == "cs" and val in ("names", "emoji"):
            await db.update_chat(cid, call_style=val)
        elif key == "cm" and int(val) in presets.CALL_MAX:
            await db.update_chat(cid, call_max=int(val))
    except (ValueError, IndexError):
        pass
    await section(cb, cid, sec)


EDIT_BACK = {"banned": "rules", "call_text": "call"}
CAN_BE_EMPTY = {"aliases", "banned", "call_text"}


@router.callback_query(F.data.startswith("mc:e:"))
async def cb_edit(cb: CallbackQuery, bot: Bot, state: FSMContext) -> None:
    _, _, cid, field = cb.data.split(":")
    if field not in FIELDS or not await _guard(cb, bot, int(cid)):
        return
    chat = await db.get_chat(int(cid))
    title, limit, hint = FIELDS[field]
    await state.set_state(McEdit.value)
    await state.update_data(chat_id=int(cid), field=field)
    current = chat[field] if field == "call_text" else esc(short(chat[field], 1500))
    await _show(cb, f"✏️ <b>{title}</b>\n\nСейчас: {current or 'пусто'}\n\n{hint}\n\n"
                    f"Пришли новое значение сообщением (до {limit} символов).",
                _kb([[("Отмена", f"mc:s:{cid}:{EDIT_BACK.get(field, 'who')}")]]))


@router.message(McEdit.value, F.text)
async def on_value(message: Message, bot: Bot, state: FSMContext) -> None:
    data = await state.get_data()
    field, cid = data["field"], data["chat_id"]
    if not await can_manage(bot, message.from_user.id, cid):
        await state.clear()
        return await message.answer(DENIED)
    title, limit, _ = FIELDS[field]
    value = message.html_text.strip() if field == "call_text" else message.text.strip()
    if field in CAN_BE_EMPTY and message.text.strip() == "-":
        value = ""
    if len(value) > limit:
        return await message.answer(f"Слишком длинно, максимум {limit} символов. Сократи и пришли ещё раз.")
    if field not in CAN_BE_EMPTY and not value:
        return await message.answer("Пустое значение не подойдёт, пришли текст.")
    await db.update_chat(cid, **{field: value})
    await state.clear()
    await message.answer(f"✅ {title}: сохранил.")
    await section(message, cid, EDIT_BACK.get(field, "who"))


# ---------- пробный ответ ----------

@router.callback_query(F.data.startswith("mc:try:"))
async def cb_try(cb: CallbackQuery, bot: Bot, state: FSMContext) -> None:
    cid = int(cb.data.split(":")[2])
    if not await _guard(cb, bot, cid):
        return
    await state.set_state(McTry.text)
    await state.update_data(chat_id=cid)
    await _show(cb, "👀 <b>Пробный ответ</b>\n\nНапиши фразу, как будто ты в чате. Отвечу так, как ответил бы там. "
                    "В чат ничего не уйдёт.", _kb([[("⬅️ К чату", f"mc:o:{cid}")]]))


@router.message(McTry.text, F.text)
async def on_try(message: Message, bot: Bot, state: FSMContext) -> None:
    cid = (await state.get_data())["chat_id"]
    chat = await db.get_chat(cid)
    if not chat or not await can_manage(bot, message.from_user.id, cid):
        await state.clear()
        return await message.answer(DENIED)
    back = _kb([[("⬅️ К чату", f"mc:o:{cid}")]])
    if not ai.enabled():
        return await message.answer("Нейросеть сейчас выключена, пробный ответ недоступен.", reply_markup=back)
    try:
        await bot.send_chat_action(message.chat.id, "typing")
    except Exception:
        pass
    reply = await talk.test_reply(chat, full_name(message.from_user.first_name, message.from_user.last_name),
                                  message.text[:500])
    await message.answer(f"💬 {esc(reply)}\n\n<i>Пиши ещё фразу или вернись к чату.</i>" if reply else
                         "Сейчас не получилось ответить: возможно, кончился дневной лимит. Попробуй позже.",
                         parse_mode="HTML", reply_markup=back)


# ---------- триггеры ----------

@router.callback_query(F.data.startswith("mc:tn:"))
async def cb_trig_new(cb: CallbackQuery, bot: Bot, state: FSMContext) -> None:
    cid = int(cb.data.split(":")[2])
    if not await _guard(cb, bot, cid):
        return
    if len(await db.list_triggers(cid)) >= MAX_TRIGGERS:
        return await cb.answer(f"Максимум {MAX_TRIGGERS} триггеров, удали лишние", show_alert=True)
    await state.set_state(McTrig.word)
    await state.update_data(chat_id=cid)
    await _show(cb, "📝 <b>Новый триггер, шаг 1 из 2</b>\n\nНа какое слово или фразу отвечать? Например: "
                    "<code>правила</code>, <code>прайс</code>, <code>адрес</code>.\n\n"
                    "<i>Сработает, когда в чате напишут ровно это слово, без разницы, большими буквами или с "
                    "восклицательным знаком.</i>", _kb([[("Отмена", f"mc:s:{cid}:trig")]]))


@router.message(McTrig.word, F.text)
async def on_trig_word(message: Message, state: FSMContext) -> None:
    word = triggers.norm(message.text)
    if not word or len(word) > 40:
        return await message.answer("Нужно слово или короткая фраза до 40 символов, не одни смайлики.")
    await state.update_data(word=word)
    await state.set_state(McTrig.reply)
    await message.answer(f"📝 <b>Шаг 2 из 2</b>\n\nСлово: <code>{esc(word)}</code>\n\nТеперь пришли ответ: текст, "
                         "фото с подписью, видео, гифку или стикер. Можно с премиум-эмодзи и жирным текстом.",
                         parse_mode="HTML")


@router.message(McTrig.reply)
async def on_trig_reply(message: Message, bot: Bot, state: FSMContext) -> None:
    data = await state.get_data()
    cid = data["chat_id"]
    if not await can_manage(bot, message.from_user.id, cid):
        await state.clear()
        return await message.answer(DENIED)
    kind, file_id, html = triggers.extract(message)
    if not kind and not html:
        return await message.answer("Пришли текст, фото, видео, гифку или стикер.")
    await db.add_trigger(cid, data["word"], kind, file_id, html[:3500])
    triggers.forget(cid)
    await state.clear()
    await message.answer(f"✅ Триггер <code>{esc(data['word'])}</code> готов. Напиши это слово в чате, и я отвечу.",
                         parse_mode="HTML")
    await section(message, cid, "trig")


@router.callback_query(F.data.startswith(("mc:td:", "mc:tx:")))
async def cb_trig_item(cb: CallbackQuery, bot: Bot) -> None:
    op, tid = cb.data.split(":")[1], int(cb.data.split(":")[2])
    trig = await db.get_trigger(tid)
    if not trig or not await _guard(cb, bot, trig["chat_id"]):
        return await cb.answer()
    cid = trig["chat_id"]
    if op == "tx":
        await db.delete_trigger(tid)
        triggers.forget(cid)
        return await section(cb, cid, "trig")
    preview = trig["text_html"] or "без текста"
    await _show(cb, f"📝 <b>Триггер</b> <code>{esc(trig['word'])}</code>\n\nОтвет: {_trig_kind(trig)}\n\n{preview}",
                _kb([[("🗑 Удалить", f"mc:tx:{tid}", "danger")], [("⬅️ Триггеры", f"mc:s:{cid}:trig")]]))


# ---------- зазывала ----------

async def _call_list(target, cid: int) -> None:
    people = await db.call_list(cid)
    rows = [[(f"❌ {short(p['name'] or str(p['user_id']), 20)}", f"mc:cr:{cid}:{p['user_id']}")
             for p in people[i:i + 2]] for i in range(0, min(len(people), 60), 2)]
    rows += [[("➕ Добавить людей", f"mc:ca:{cid}", "success")], [("⬅️ Зазывала", f"mc:s:{cid}:call")]]
    await _show(target, f"📋 <b>Мой список для зазывалы</b>: {len(people)}\n\nКого звать, когда выбрано "
                        "Мой список. Нажми на человека, чтобы убрать.", _kb(rows))


@router.callback_query(F.data.startswith("mc:cl:"))
async def cb_call_list(cb: CallbackQuery, bot: Bot, state: FSMContext) -> None:
    cid = int(cb.data.split(":")[2])
    if await _guard(cb, bot, cid):
        await state.clear()
        await _call_list(cb, cid)


@router.callback_query(F.data.startswith("mc:cr:"))
async def cb_call_remove(cb: CallbackQuery, bot: Bot) -> None:
    _, _, cid, uid = cb.data.split(":")
    if await _guard(cb, bot, int(cid)):
        await db.call_remove(int(cid), int(uid))
        await _call_list(cb, int(cid))


@router.callback_query(F.data.startswith("mc:ca:"))
async def cb_call_add(cb: CallbackQuery, bot: Bot, state: FSMContext) -> None:
    cid = int(cb.data.split(":")[2])
    if not await _guard(cb, bot, cid):
        return
    await state.set_state(McCall.add)
    await state.update_data(chat_id=cid)
    await _show(cb, "➕ <b>Добавить в список</b>\n\nПришли юзернеймы или имена через пробел или с новой строки, "
                    "например:\n<code>@vasya @anya Олег</code>\n\nИщу среди тех, кто писал в чате при мне.",
                _kb([[("Готово", f"mc:cl:{cid}")]]))


@router.message(McCall.add, F.text)
async def on_call_add(message: Message, bot: Bot, state: FSMContext) -> None:
    cid = (await state.get_data())["chat_id"]
    if not await can_manage(bot, message.from_user.id, cid):
        await state.clear()
        return await message.answer(DENIED)
    added, missed = [], []
    for token in message.text.replace(",", " ").split()[:50]:
        user = await db.find_user(cid, token)
        if user:
            await db.call_add(cid, user["user_id"], user["name"])
            added.append(user["name"])
        else:
            missed.append(token)
    text = f"✅ Добавил: {esc(', '.join(added))}" if added else "Никого не нашёл."
    if missed:
        text += f"\nНе нашёл: {esc(', '.join(missed))} (они ещё не писали в чате при мне)"
    await message.answer(text + "\n\nПришли ещё или нажми Готово.", parse_mode="HTML",
                         reply_markup=_kb([[("Готово", f"mc:cl:{cid}")]]))


@router.callback_query(F.data.startswith("mc:run:"))
async def cb_call_run(cb: CallbackQuery, bot: Bot) -> None:
    cid = int(cb.data.split(":")[2])
    if not await _guard(cb, bot, cid):
        return
    n = await caller.start(bot, await db.get_chat(cid), starter=cb.from_user.id)
    if n == -1:
        return await cb.answer("Уже зову. Остановить: /stopcall в чате", show_alert=True)
    if n == 0:
        return await cb.answer("Некого звать: никто из выбранных ещё не писал в чате при мне", show_alert=True)
    await cb.answer(f"📣 Зову {n} человек в чате", show_alert=True)


# ---------- стереть память ----------

@router.callback_query(F.data.startswith("mc:w:"))
async def cb_wipe(cb: CallbackQuery, bot: Bot) -> None:
    cid = int(cb.data.split(":")[2])
    if await _guard(cb, bot, cid):
        await _show(cb, "🧹 Стереть, что бот помнит о переписке и людях в этом чате? Настройки останутся.",
                    _kb([[("Да, стереть", f"mc:W:{cid}", "danger"), ("Отмена", f"mc:o:{cid}")]]))


@router.callback_query(F.data.startswith("mc:W:"))
async def cb_wipe_ok(cb: CallbackQuery, bot: Bot) -> None:
    cid = int(cb.data.split(":")[2])
    if await _guard(cb, bot, cid):
        await db.clear_memory(cid)
        await cb.answer("🧹 Память стёрта", show_alert=True)
        await card(cb, cid, cb.from_user.id)


# ---------- перенос чата ----------

async def can_move_from(bot: Bot, user_id: int, src: int) -> bool:
    """Из рабочего чата переносить может тот, кто им управляет. Из пропавшего: владелец бота или тот, кто
    когда-то добавил бота (Telegram уже не скажет, кто там админ)."""
    chat = await db.get_chat(src)
    if not chat:
        return False
    if user_id in config.OWNER_IDS:
        return True
    if chat["active"]:
        return await can_manage(bot, user_id, src)
    return chat["added_by"] == user_id


async def _rights_only(bot: Bot, user_id: int, chat_id: int) -> bool:
    """Права в новом чате, даже если его ещё не одобрили."""
    if user_id in config.OWNER_IDS:
        return True
    try:
        m = await bot.get_chat_member(chat_id, user_id)
        return m.status == "creator" or (m.status == "administrator" and bool(getattr(m, "can_promote_members", False)))
    except Exception:
        return False


async def move_targets(bot: Bot, user_id: int, src: int) -> list:
    if user_id in config.OWNER_IDS:
        rows = [c for c in await db.list_chats(active_only=False) if c["active"]]
    else:
        rows = await db.candidate_chats(user_id, approved_only=False)
    return [c for c in rows if c["chat_id"] != src and await _rights_only(bot, user_id, c["chat_id"])]


@router.callback_query(F.data == "mc:lost")
async def cb_lost(cb: CallbackQuery) -> None:
    lost = await db.lost_chats(cb.from_user.id)
    rows = [[(f"🕳 {short(c['title'] or str(c['chat_id']), 40)}", f"mc:mv:{c['chat_id']}")] for c in lost[:20]]
    await _show(cb, "📦 <b>Пропавшие чаты</b>\n\nЧаты, которые ты добавлял, но бота там больше нет. Выбери, "
                    "откуда перенести всё в новый чат.", _kb(rows + [[("⬅️ Мои чаты", "mc:list")]]))


@router.callback_query(F.data.startswith("mc:mv:"))
async def cb_move(cb: CallbackQuery, bot: Bot) -> None:
    src = int(cb.data.split(":")[2])
    if not await can_move_from(bot, cb.from_user.id, src):
        return await cb.answer(DENIED, show_alert=True)
    chat = await db.get_chat(src)
    targets = await move_targets(bot, cb.from_user.id, src)
    me = await bot.me()
    if not targets:
        return await _show(cb, "📦 <b>Куда переносим?</b>\n\nСначала добавь бота в новую группу, где ты создатель или "
                               "админ с правом назначать админов. Потом вернись сюда, одобрения ждать не нужно.",
                           _kb([[("➕ Добавить бота в группу", f"https://t.me/{me.username}?startgroup=true", "success")],
                                [("🔄 Проверить снова", f"mc:mv:{src}")], [("⬅️ Мои чаты", "mc:list")]]))
    rows = [[(f"➡️ {short(c['title'] or str(c['chat_id']), 40)}", f"mc:mt:{src}:{c['chat_id']}")] for c in targets[:20]]
    await _show(cb, f"📦 <b>Перенос из {esc(chat['title'] or str(src))}</b>\n\nВыбери новый чат. Бот уже должен "
                    "быть добавлен туда.", _kb(rows + [[("⬅️ Мои чаты", "mc:list")]]))


@router.callback_query(F.data.startswith(("mc:mt:", "mc:MT:")))
async def cb_move_to(cb: CallbackQuery, bot: Bot) -> None:
    _, op, src, dst = cb.data.split(":")
    src, dst = int(src), int(dst)
    if not await can_move_from(bot, cb.from_user.id, src) or not await _rights_only(bot, cb.from_user.id, dst):
        return await cb.answer(DENIED, show_alert=True)
    a, b = await db.get_chat(src), await db.get_chat(dst)
    if op == "mt":
        from bot.services.approval import until_text
        rent = f"\n📅 Аренда до {until_text(a['rent_until'])} перейдёт в новый чат." if a["rent_until"] else ""
        return await _show(cb, f"📦 Перенести всё из <b>{esc(a['title'] or '')}</b> в <b>{esc(b['title'] or '')}</b>?\n\n"
                               "Настройки нового чата заменятся настройками старого, память о людях, репутация, "
                               f"топ викторины и триггеры добавятся (монеты и питомцы у людей общие, их переносить не нужно).{rent}\n\nСтарый чат после переноса выключится.",
                           _kb([[("✅ Да, перенести", f"mc:MT:{src}:{dst}", "success")], [("Отмена", f"mc:mv:{src}")]]))
    counts = await db.move_chat(src, dst)
    triggers.forget(dst)
    from bot import notify
    await notify.owners(bot, f"📦 Перенос чата: {esc(a['title'] or str(src))} → {esc(b['title'] or str(dst))} "
                             f"(перенёс {esc(cb.from_user.full_name)})")
    await cb.answer("✅ Перенесено", show_alert=True)
    try:
        await cb.message.answer(f"✅ Готово! Перенёс в <b>{esc(b['title'] or '')}</b>: настройки, людей "
                                f"({counts.get('users', 0)}), репутацию, викторину и триггеры "
                                f"({counts.get('triggers', 0)}).", parse_mode="HTML")
    except Exception:
        pass
    await card(cb.message, dst, cb.from_user.id)


# ---------- экспорт и импорт настроек ----------

@router.callback_query(F.data.startswith("mc:ex:"))
async def cb_export(cb: CallbackQuery, bot: Bot) -> None:
    import json
    from aiogram.types import BufferedInputFile
    cid = int(cb.data.split(":")[2])
    if not await _guard(cb, bot, cid):
        return
    chat = await db.get_chat(cid)
    data = {"format": "baxi-settings", "version": 1, "title": chat["title"], "settings": await db.chat_settings(cid),
            "triggers": [{k: t[k] for k in ("word", "media_kind", "file_id", "text_html")}
                         for t in await db.list_triggers(cid)]}
    raw = json.dumps(data, ensure_ascii=False, indent=1).encode()
    await cb.answer()
    await bot.send_document(cb.from_user.id, BufferedInputFile(raw, filename=f"baxi-settings-{abs(cid)}.json"),
                            caption="📤 Настройки бота. Загрузить в любой чат: Мои чаты → чат → 🧰 → 📥 Загрузить")


@router.callback_query(F.data.startswith("mc:im:"))
async def cb_import(cb: CallbackQuery, bot: Bot, state: FSMContext) -> None:
    cid = int(cb.data.split(":")[2])
    if not await _guard(cb, bot, cid):
        return
    await state.set_state(McImport.file)
    await state.update_data(chat_id=cid)
    await _show(cb, "📥 <b>Загрузить настройки</b>\n\nПришли файл baxi-settings-....json, который скачивал раньше. "
                    "Настройки этого чата заменятся, триггеры добавятся.", _kb([[("Отмена", f"mc:s:{cid}:tools")]]))


@router.message(McImport.file, F.document)
async def on_import(message: Message, bot: Bot, state: FSMContext) -> None:
    import io
    import json
    cid = (await state.get_data())["chat_id"]
    if not await can_manage(bot, message.from_user.id, cid):
        await state.clear()
        return await message.answer(DENIED)
    if (message.document.file_size or 0) > 1024 * 1024:
        return await message.answer("Файл слишком большой, это не файл настроек.")
    buf = io.BytesIO()
    await bot.download(message.document, destination=buf)
    try:
        data = json.loads(buf.getvalue().decode())
        if data.get("format") != "baxi-settings":
            raise ValueError
    except Exception:
        return await message.answer("Это не файл настроек Бакси. Нужен baxi-settings-....json.")
    n = await db.apply_settings(cid, data.get("settings", {}))
    t = 0
    for trig in data.get("triggers", [])[:MAX_TRIGGERS]:
        if trig.get("word"):
            await db.add_trigger(cid, str(trig["word"])[:40], str(trig.get("media_kind", "")),
                                 str(trig.get("file_id", "")), str(trig.get("text_html", ""))[:3500])
            t += 1
    triggers.forget(cid)
    await state.clear()
    await message.answer(f"✅ Загрузил: настроек {n}, триггеров {t}.")
    await card(message, cid, message.from_user.id)


# ---------- свои вопросы дня ----------

@router.callback_query(F.data.startswith(("mc:qa:", "mc:qn:", "mc:qx:")))
async def cb_qday(cb: CallbackQuery, bot: Bot, state: FSMContext) -> None:
    op, cid = cb.data.split(":")[1], int(cb.data.split(":")[2])
    if not await _guard(cb, bot, cid):
        return
    if op == "qx":
        await db.update_chat(cid, qday_queue="")
        return await section(cb, cid, "qday")
    if op == "qn":
        from bot.services import qday
        await qday.post(bot, await db.get_chat(cid))
        await cb.answer("❓ Задал вопрос в чате", show_alert=True)
        return await section(cb, cid, "qday")
    await state.set_state(McQday.add)
    await state.update_data(chat_id=cid)
    await _show(cb, "✏️ <b>Свои вопросы дня</b>\n\nПришли вопросы, каждый с новой строки. Они встанут в очередь, "
                    "по одному в день.", _kb([[("Готово", f"mc:s:{cid}:qday")]]))


@router.message(McQday.add, F.text)
async def on_qday_add(message: Message, bot: Bot, state: FSMContext) -> None:
    cid = (await state.get_data())["chat_id"]
    if not await can_manage(bot, message.from_user.id, cid):
        await state.clear()
        return await message.answer(DENIED)
    chat = await db.get_chat(cid)
    new = [" ".join(q.split())[:300] for q in message.text.splitlines() if q.strip()]
    queue = [q for q in (chat["qday_queue"] or "").splitlines() if q.strip()] + new
    await db.update_chat(cid, qday_queue="\n".join(queue[:100]))
    await message.answer(f"✅ Добавил {len(new)}, в очереди {min(len(queue), 100)}. Пришли ещё или нажми Готово.",
                         reply_markup=_kb([[("Готово", f"mc:s:{cid}:qday")]]))


# ---------- 🛡 Модерация: данные модератора (dalmatinec/baxi-guard) ----------

GUARD_KINDS = [("mute", "мутов"), ("warn", "предупреждений"), ("ban", "банов"), ("kick", "киков"), ("spam", "спама")]


def _guard_counts(st: dict) -> str:
    return ", ".join(f"{name} {int(st.get(k, 0) or 0)}" for k, name in GUARD_KINDS)


async def guard_screen(target, chat_id: int) -> None:
    from bot.services import guardlink
    c = await db.get_chat(chat_id)
    tease = "✅ вкл" if c["guard_tease"] else "▫️ выкл"
    lines = [f"🛡 <b>Модерация</b> · {esc(c['title'] or str(chat_id))}", ""]
    rows: list[list[tuple]] = []
    info = await guardlink.guard_overview(chat_id) if guardlink.enabled() else None
    if not guardlink.enabled():
        lines.append("Модератор не подключён. Это отдельный бот: мут, бан, предупреждения, стоп-слова, "
                     "антиспам, режим атаки. Спроси у владельца бота, как его добавить.")
    elif info is None:
        lines.append("Модератор сейчас не отвечает, данные появятся, когда он снова будет на связи.")
    else:
        st = info["settings"]
        if not st.get("known"):
            lines.append("Модератора нет в этом чате. Добавь его администратором, и здесь появятся его данные.")
        else:
            def on(v) -> str:
                return "✅" if v else "▫️"
            lines += [f"{on(st.get('stopwords'))} стоп-слова   {on(st.get('antispam'))} антиспам",
                      f"{on(st.get('service'))} чистка служебных   {on(st.get('attack'))} режим атаки",
                      f"⚠️ предупреждений до наказания: {st.get('warn_limit', 3)}",
                      "", f"<b>За сутки:</b> {_guard_counts(info['day'])}",
                      f"<b>За неделю:</b> {_guard_counts(info['week'])}"]
            if not st.get("active", True):
                lines += ["", "⏸ Модерация в этом чате сейчас не активна."]
        username = (info["ping"] or {}).get("bot") or ""
        if username:
            rows.append([("⚙️ Настроить модерацию", f"https://t.me/{username}?start=s_{chat_id}", "primary")])
    lines += ["", f"😏 Подколки: {tease}. Когда модератор наказывает, я иногда подкалываю в своём характере "
                  "(не чаще раза в 10 минут). Предупреждения репутацию не снимают."]
    rows.append([(f"😏 Подколки: {tease}", f"mc:gt:{chat_id}")])
    rows.append([("⬅️ К чату", f"mc:o:{chat_id}")])
    await _show(target, "\n".join(lines), _kb(rows))


@router.callback_query(F.data.startswith(("mc:g:", "mc:gt:")))
async def cb_guard(cb: CallbackQuery, bot: Bot, state: FSMContext) -> None:
    await state.clear()
    parts = cb.data.split(":")
    chat_id = int(parts[2])
    if not await _guard(cb, bot, chat_id):
        return
    if parts[1] == "gt":
        c = await db.get_chat(chat_id)
        await db.update_chat(chat_id, guard_tease=0 if c["guard_tease"] else 1)
    await guard_screen(cb, chat_id)

