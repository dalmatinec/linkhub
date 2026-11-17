"""Общее для экономики в чате и в личке: тексты профиля и топов, карточка питомца, кнопки."""

import asyncio
import time

from aiogram import Bot
from aiogram.types import BufferedInputFile, InlineKeyboardButton, InlineKeyboardMarkup, Message, User

from bot.economy import cards, catalog, hooks, service, store
from bot.services.out import reply_params, say
from bot.textutil import esc, full_name, mention

MEDALS = ["🥇", "🥈", "🥉"]
_render = asyncio.Semaphore(2)            # не больше 2 картинок одновременно: память сервера не скачет
_card_seen: dict[tuple[int, int], float] = {}
CARD_COOLDOWN = 15                        # одну и ту же карточку в чате не чаще раза в 15 секунд


def name_of(user: User) -> str:
    return full_name(user.first_name, user.last_name, user.username)


def kb(rows: list[list[tuple]]) -> InlineKeyboardMarkup:
    """Ряды кнопок: (текст, callback или https-ссылка, стиль). Пустые ряды пропускаются."""
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=t, url=d, style=s[0] if s else None) if d.startswith("http") else
        InlineKeyboardButton(text=t, callback_data=d, style=s[0] if s else None) for t, d, *s in row]
        for row in rows if row])


def bar(part: float, total: float, width: int = 10) -> str:
    full = max(0, min(width, round(width * part / total))) if total else 0
    return "▰" * full + "▱" * (width - full)


def pet_title(pet) -> str:
    """Пушок · Кошка, 3 ур. Если клички нет, просто Кошка, 3 ур."""
    info = catalog.PETS[pet["species"]]
    name = f"<b>{esc(pet['name'])}</b> · {info['name']}" if pet["name"] != info["name"] else f"<b>{info['name']}</b>"
    return f"{info['emoji']} {name}, {service.pet_level(pet)} ур."


async def profile_lines(user: User) -> list[str]:
    """Монеты, уровень, опыт, бонус и питомец: для профиля в личке."""
    w = await store.wallet(user.id, name_of(user))
    lvl = w["level"]
    lo, hi = catalog.xp_for(lvl), catalog.xp_for(lvl + 1)
    pet = await store.pet(user.id)
    pet_line = (f"{pet_title(pet)} · сытость {int(service.satiety(pet))}%" if pet else "пока нет")
    bonus = (f"можно забрать 🎁 (+{service.next_bonus(w['streak'] if w['bonus_day'] else 0, lvl)} 🪙)"
             if service.bonus_ready(w) else f"забран ✅, серия {w['streak']} дн.")
    return [f"🪙 Монеты: <b>{w['coins']}</b>",
            f"🌍 Общий уровень <b>{lvl}</b> · {catalog.title_for(lvl)} (#{await store.global_place(user.id)} среди всех)",
            f"📈 {bar(w['xp'] - lo, hi - lo, 8)} {w['xp'] - lo}/{hi - lo}",
            f"🎁 Бонус дня: {bonus}",
            f"🐾 Питомец: {pet_line}",
            f"🎖 Плюшки: {catalog.perks_text(catalog.perks_for(lvl))}",
            *await chat_ranks_lines(user.id)]


async def chat_ranks_lines(user_id: int) -> list[str]:
    """Ранги человека в чатах, где он пишет: для профиля."""
    rows = await store.my_chat_ranks(user_id, limit=3)
    if not rows:
        return ["🏅 Ранги в чатах: пока нет, пиши в чатах с ботом"]
    return ["🏅 <b>Ранги в чатах:</b>"] + [f"   • {esc(r['title'] or 'чат')[:30]}: {r['level']} · "
                                          f"{catalog.title_for(r['level'])}" for r in rows]


def _num(n: int) -> str:
    return f"{n:,}".replace(",", " ")


def _plural(n: int, one: str, few: str, many: str) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


async def rank_card(chat_id: int, user: User) -> str:
    """/me в чате: компактная карточка. Кто это, активность, ранг, репутация, монеты, питомец и
    модерация (предупреждения, текущий мут или бан, история с причинами в свёрнутой цитате)."""
    import datetime
    from bot import config, db
    from bot.services import guardlink
    name = name_of(user)
    r = await store.chat_rank(chat_id, user.id, name)
    w = await store.wallet(user.id, name)
    place, total = await store.chat_rank_place(chat_id, user.id)
    lo, hi = catalog.xp_for(r["level"]), catalog.xp_for(r["level"] + 1)
    pet = await store.pet(user.id)
    row = await db.get_user(chat_id, user.id)
    chat = await db.get_chat(chat_id)
    msgs = row["msg_count"] if row else 0
    first = row["first_seen"] if row and "first_seen" in row.keys() else 0

    head = f"👤 {mention(user.id, name)}" + (f" · @{esc(user.username)}" if user.username else "")
    lines = [head, f"🆔 <code>{user.id}</code>", ""]
    lines.append(f"🏅 Ранг <b>{r['level']}</b> · {catalog.title_for(r['level'])}"
                 + (f" · {place} из {total}" if r["xp"] else ""))
    lines.append(f"📈 {bar(r['xp'] - lo, hi - lo)} {r['xp'] - lo}/{hi - lo}")
    activity = f"💬 {_num(msgs)} {_plural(msgs, 'сообщение', 'сообщения', 'сообщений')}"
    if first:
        activity += " · 📅 с " + datetime.datetime.fromtimestamp(first, config.TZ).strftime("%d.%m.%Y")
    lines.append(activity)
    if not chat or chat["rep"]:
        rep = await db.rep_get(chat_id, user.id)
        lines.append(f"💜 Репутация <b>{rep}</b>" + (f" · {await db.rep_place(chat_id, user.id)} место" if rep else ""))
    lines.append(f"🪙 <b>{_num(w['coins'])}</b> · 🌍 ур. {w['level']} (#{await store.global_place(user.id)})")
    if pet:
        lines.append(f"🐾 {pet_title(pet)}")
    status, history = await guardlink.card_lines(chat_id, user.id)
    lines += ["", status]
    text = "\n".join(lines)
    if history:
        text += "\n<blockquote expandable>" + "\n".join(history) + "</blockquote>"
    return text


async def send_pet(bot: Bot, chat_id: int, user: User, bot_name: str, reply_to: Message | None = None,
                   extra: list | None = None) -> bool:
    """Карточка питомца картинкой (или текстом без Pillow). False, если питомца нет."""
    pet = await store.pet(user.id)
    if not pet:
        return False
    sat, lvl, power = service.satiety(pet), service.pet_level(pet), service.pet_power(pet)
    caption = (f"{pet_title(pet)}\n"
               f"Хозяин: {mention(user.id, name_of(user))}\n"
               f"🍖 Сытость {int(sat)}% · 💪 сила {power}"
               + (f"\n🕓 Последний раз кормил: {esc(pet['fed_by'])}" if pet["fed_by"] else "")
               + ("\n😿 Голодный питомец не растёт, покорми его" if sat < catalog.PET_XP_HUNGRY else ""))
    markup = hooks.feed_kb(user.id, pet["species"], extra)
    async with _render:
        image = await asyncio.to_thread(cards.pet_card, pet, sat, lvl, power, name_of(user), bot_name)
    if image is None:
        await say(bot, chat_id, caption, reply_to=reply_to, markup=markup)
    else:
        await bot.send_photo(chat_id, BufferedInputFile(image, "pet.jpg"), caption=caption, parse_mode="HTML",
                             reply_markup=markup, reply_parameters=reply_params(reply_to))
    return True


def card_allowed(chat_id: int, user_id: int) -> bool:
    """Защита от спама карточками в чате."""
    now = time.time()
    if now - _card_seen.get((chat_id, user_id), 0) < CARD_COOLDOWN:
        return False
    _card_seen[(chat_id, user_id)] = now
    if len(_card_seen) > 5000:
        _card_seen.clear()
    return True


async def pets_top_text(chat_id: int) -> str:
    rows = await service.pet_top(chat_id)
    if not rows:
        return "🐾 <b>Топ питомцев</b>\n\nПока ни у кого нет питомца. Завести можно в личке бота: магазин → питомцы"
    lines = ["🐾 <b>Топ питомцев</b>", ""]
    for i, p in enumerate(rows):
        place = MEDALS[i] if i < 3 else f"{i + 1}."
        lines.append(f"{place} {pet_title(p)} · {mention(p['user_id'], p['owner'])} · 💪 {service.pet_power(p)}")
    return "\n".join(lines)


TOPS = {"rich": "🪙 <b>Богачи чата</b>", "ranks": "🏅 <b>Ранги этого чата</b>",
        "global": "🌍 <b>Общий топ: все чаты с ботом</b>"}


async def top_text(chat_id: int, kind: str) -> str:
    """rich: монеты среди людей чата; ranks: ранг в этом чате; global: общий уровень во всех чатах."""
    rows = await {"rich": store.rich_top, "ranks": store.chat_rank_top}[kind](chat_id) if kind != "global" \
        else await store.global_top()
    title = TOPS[kind]
    if not rows:
        return f"{title}\n\nПока пусто. Пишите в чат, монеты и опыт капают сами."
    lines = [title, ""]
    for i, r in enumerate(rows):
        place = MEDALS[i] if i < 3 else f"{i + 1}."
        value = f"{r['coins']} 🪙" if kind == "rich" else f"{r['level']} · {catalog.title_for(r['level'])}"
        lines.append(f"{place} {mention(r['user_id'], r['name'])}: <b>{value}</b>")
    return "\n".join(lines)


TOPS_KB_ROWS = [[("🏅 Ранги чата", "eco:ranks"), ("🌍 Общий топ", "eco:global")],
                [("🪙 Богачи", "eco:rich"), ("🐾 Питомцы", "eco:pets")],
                [("💜 Репутация", "gm:rep_top"), ("🧠 Викторина", "gm:quiz_top")]]


EARN_TEXT = (
    "💡 <b>Как заработать монеты</b>\n\n"
    "💬 <b>Общайся в чатах</b>, где есть {bot}: за сообщения капают монеты и опыт (не чаще 2 раз в минуту, "
    "короткие ок и + не считаются).\n"
    "🎁 <b>Бонус дня</b>: напиши в чате <b>бонус</b> или нажми кнопку в профиле. Каждый день подряд бонус больше, "
    f"от {catalog.BONUS_BASE} до {catalog.BONUS_MAX} 🪙.\n"
    "🆙 <b>Новый уровень</b>: за каждый уровень награда, чем выше уровень, тем больше.\n"
    "🎲 <b>Кости</b>: ответь в чате на сообщение соперника <b>кости 100</b>. У кого на кубике больше, тот забирает банк.\n"
    "💸 <b>Подарки</b>: друзья могут передать монеты: ответом <b>передать 100</b>.\n"
    "💳 <b>Пополнить</b>: звёздами Telegram или криптой (USDT), если не хочется ждать.\n\n"
    "🏅 <b>Самые активные недели</b>: в воскресенье вечером топ-3 по сообщениям в каждом чате получают "
    f"{catalog.WEEKLY_PRIZES[0]}, {catalog.WEEKLY_PRIZES[1]} и {catalog.WEEKLY_PRIZES[2]} 🪙.\n\n"
    "🎖 <b>Плюшки ранга</b>: чем выше уровень, тем выгоднее.\n"
    + "\n".join(f"• {lvl} ур. {catalog.title_for(lvl)}: {catalog.perks_text(catalog.perks_for(lvl))}"
                for lvl, *_ in catalog.RANK_PERKS[1:]) + "\n\n"
    "🐾 <b>На что тратить</b>: питомец (от улитки до дракона), корм для него, свой ник навсегда.\n"
    "Монеты и питомец общие: один кошелёк во всех чатах."
)
