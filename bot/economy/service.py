"""Логика экономики без Telegram: начисления за сообщения, бонус дня, покупки, питомцы, кости.
Кошелёк и питомец общие на человека (во всех чатах одни). Обработчики: bot/handlers/economy/,
картинки: bot/economy/cards.py, цифры: bot/economy/catalog.py."""

import random
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from bot import config
from bot.economy import catalog, store


def today() -> str:
    return datetime.now(config.TZ).strftime("%Y-%m-%d")


# ---------- опыт и монеты за сообщения ----------

async def on_message(chat_id: int, user_id: int, name: str, text: str) -> dict:
    """Сообщение в чате. Два счёта опыта:
      ранг в этом чате: не чаще раза в 30 секунд в этом чате;
      общий уровень и монеты: не чаще раза в 30 секунд во всех чатах вместе (плюшки зависят от него).
    Возвращает {'chat': (старый, новый) или None, 'global': (старый, новый) или None}."""
    out = {"chat": None, "global": None}
    text = (text or "").strip()
    if len(text) < catalog.MIN_TEXT or text.startswith("/"):
        return out
    now = time.time()
    r = await store.chat_rank(chat_id, user_id, name)
    if now - r["last_award"] >= catalog.AWARD_COOLDOWN:
        cxp = r["xp"] + random.randint(*catalog.XP_PER_MSG)
        clevel = catalog.level_for(cxp)
        await store.update_chat_rank(chat_id, user_id, xp=cxp, level=clevel, last_award=now)
        if clevel > r["level"]:
            out["chat"] = (r["level"], clevel)
    out["global"] = await _global_award(user_id, name, now)
    return out


async def _global_award(user_id: int, name: str, now: float) -> tuple[int, int] | None:
    w = await store.wallet(user_id, name)
    if now - w["last_award"] < catalog.AWARD_COOLDOWN:
        return None
    xp = w["xp"] + random.randint(*catalog.XP_PER_MSG)
    got = random.randint(*catalog.COINS_PER_MSG) + catalog.perks_for(w["level"])["coins"]   # плюшка ранга
    level = catalog.level_for(xp)
    await store.update_wallet(user_id, xp=xp, coins=w["coins"] + got, earned=w["earned"] + got, level=level,
                              last_award=now)
    pet = await store.pet(user_id)
    if pet and satiety(pet) >= catalog.PET_XP_HUNGRY:
        await store.update_pet(user_id, xp=pet["xp"] + 1)  # сытый питомец растёт вместе с хозяином
    return (w["level"], level) if level > w["level"] else None


# ---------- бонус дня ----------

def bonus_ready(w) -> bool:
    return w["bonus_day"] != today()


async def claim_bonus(user_id: int, name: str) -> tuple[int, int] | None:
    """Бонус раз в день. Возвращает (сколько дали, серия дней) или None, если уже забирал."""
    w = await store.wallet(user_id, name)
    if not bonus_ready(w):
        return None
    yesterday = (datetime.now(config.TZ) - timedelta(days=1)).strftime("%Y-%m-%d")
    streak = w["streak"] + 1 if w["bonus_day"] == yesterday else 1
    amount = min(catalog.BONUS_BASE + catalog.BONUS_STEP * (streak - 1), catalog.BONUS_MAX)
    amount = round(amount * (100 + catalog.perks_for(w["level"])["bonus"]) / 100)   # плюшка ранга
    await store.update_wallet(user_id, coins=w["coins"] + amount, earned=w["earned"] + amount, bonus_day=today(),
                              streak=streak)
    return amount, streak


def next_bonus(streak: int, level: int = 1) -> int:
    base = min(catalog.BONUS_BASE + catalog.BONUS_STEP * streak, catalog.BONUS_MAX)
    return round(base * (100 + catalog.perks_for(level)["bonus"]) / 100)


# ---------- питомцы ----------

def satiety(pet) -> float:
    """Текущая сытость с учётом времени с последнего кормления."""
    hours = (time.time() - pet["fed_at"]) / 3600
    return max(0.0, pet["satiety"] - hours * catalog.PET_HUNGER_PER_HOUR)


def pet_level(pet) -> int:
    return catalog.pet_level_for(pet["xp"])


def pet_power(pet) -> int:
    return catalog.PETS[pet["species"]]["power"] + pet_level(pet)


def can_buy(current, species: str) -> str:
    """'' если можно взять этого питомца, иначе причина."""
    if species not in catalog.PETS:
        return "такого питомца нет"
    if current and catalog.PET_ORDER.index(current["species"]) >= catalog.PET_ORDER.index(species):
        return "у тебя уже такой питомец или круче"
    return ""


async def buy_pet(user_id: int, owner: str, species: str) -> str:
    """Покупка за монеты. Возвращает '' при успехе или причину отказа."""
    why = can_buy(await store.pet(user_id), species)
    if why:
        return why
    price = catalog.PETS[species]["price"]
    await store.wallet(user_id, owner)
    if not await store.spend(user_id, price):
        return f"не хватает монет, нужно {price} 🪙"
    await store.set_pet(user_id, owner, species, catalog.PETS[species]["name"])
    return ""


async def feed(owner_id: int, feeder_id: int, feeder: str, kind: str = "food") -> dict:
    """Кормит питомца хозяина owner_id. Платит тот, кто нажал (можно кормить и чужого).
    Возвращает {'error': ...} или {'food': ..., 'satiety': ..., 'pet': ...}."""
    pet = await store.pet(owner_id)
    if not pet:
        return {"error": "у тебя ещё нет питомца, загляни в магазин" if owner_id == feeder_id else "питомца уже нет"}
    food = next((f for f in catalog.foods(pet["species"]) if f["key"] == kind), None)
    if not food:
        return {"error": "такого корма нет"}
    now_sat = satiety(pet)
    if now_sat >= catalog.PET_FULL:
        return {"error": f"{pet['name']} сыт и отказывается есть 😼"}
    w = await store.wallet(feeder_id, feeder)
    discount = catalog.perks_for(w["level"])["food"]       # плюшка ранга: скидка на корм
    food = dict(food, price=max(1, round(food["price"] * (100 - discount) / 100)), discount=discount)
    if not await store.spend(feeder_id, food["price"]):
        return {"error": f"не хватает монет: {food['name']} стоит {food['price']} 🪙"}
    new_sat = min(100.0, now_sat + food["plus"])
    await store.update_pet(owner_id, satiety=new_sat, fed_at=time.time(), xp=pet["xp"] + food["xp"],
                           fed_by=f"{feeder} · {food['name']} {food['emoji']}", warned=0)
    return {"food": food, "satiety": int(new_sat), "pet": await store.pet(owner_id)}


def clean_pet_name(name: str) -> str:
    return " ".join((name or "").split())[:20]


async def rename_pet(user_id: int, name: str) -> str:
    name = clean_pet_name(name)
    if not name or "http" in name.lower() or "@" in name or name.startswith("/"):
        return "кличка до 20 символов, без ссылок и @"
    if not await store.pet(user_id):
        return "у тебя ещё нет питомца"
    await store.update_pet(user_id, name=name)
    return ""


async def hungry_pets() -> list:
    """Питомцы, которые проголодались и о которых хозяину ещё не писали."""
    return [p for p in await store.all_pets() if not p["warned"] and satiety(p) < catalog.PET_XP_HUNGRY]


async def pet_top(chat_id: int, limit: int = 10) -> list:
    pets = await store.pets_in_chat(chat_id)
    return sorted(pets, key=pet_power, reverse=True)[:limit]


# ---------- переводы и ник ----------

async def gift(from_id: int, from_name: str, to_id: int, to_name: str, amount: int) -> str:
    if from_id == to_id:
        return "себе переводить нельзя 🙃"
    if amount < catalog.GIFT_MIN:
        return f"минимум {catalog.GIFT_MIN} 🪙"
    await store.wallet(from_id, from_name)
    if not await store.spend(from_id, amount):
        return "не хватает монет"
    await store.add_coins(to_id, amount, to_name)
    return ""


async def buy_look(user_id: int) -> str:
    """Свой ник и премиум-эмодзи навсегда за монеты. Сам вид настраивается в личке бота."""
    from bot import db
    perks = await db.get_perks(user_id)
    if perks and perks["look_forever"]:
        return "у тебя уже есть свой ник навсегда"
    if not await store.spend(user_id, catalog.NICK_PRICE):
        return f"нужно {catalog.NICK_PRICE} 🪙"
    await db.set_perks(user_id, look_forever=1)
    return ""


# ---------- кости: ставка ответом на сообщение (игра идёт в чате, монеты общие) ----------

@dataclass
class Duel:
    chat_id: int
    a: int
    a_name: str
    b: int
    b_name: str
    bet: int
    accepted: bool = False
    rolls: dict = field(default_factory=dict)     # кто сколько выбросил
    created: float = field(default_factory=time.time)


DUELS: dict[int, Duel] = {}       # одна игра в кости на чат
DUEL_TIMEOUT = 180


def active_duel(chat_id: int) -> Duel | None:
    """Игра в чате, если она ещё не протухла (протухшие разбирает refund_expired)."""
    d = DUELS.get(chat_id)
    return d if d and time.time() - d.created <= DUEL_TIMEOUT else None


async def start_duel(chat_id: int, a: int, a_name: str, b: int, b_name: str, bet: int) -> str:
    await refund_expired()
    if not catalog.DICE_MIN <= bet <= catalog.DICE_MAX:
        return f"ставка от {catalog.DICE_MIN} до {catalog.DICE_MAX} 🪙"
    if active_duel(chat_id):
        return "в чате уже идёт игра в кости, подождите"
    if a == b:
        return "с собой играть нельзя 🙃"
    w = await store.wallet(a, a_name)
    if w["coins"] < bet:
        return f"у тебя только {w['coins']} 🪙"
    DUELS[chat_id] = Duel(chat_id, a, a_name, b, b_name, bet)
    return ""


async def accept_duel(chat_id: int, user_id: int) -> str:
    d = active_duel(chat_id)
    if not d or d.accepted:
        return "игра уже закончилась"
    if user_id != d.b:
        return "это не тебе вызов"
    await store.wallet(d.b, d.b_name)
    if not await store.spend(d.a, d.bet):
        DUELS.pop(chat_id, None)
        return "у вызвавшего уже не хватает монет"
    if not await store.spend(d.b, d.bet):
        await store.add_coins(d.a, d.bet)
        DUELS.pop(chat_id, None)
        return f"у тебя не хватает монет, нужно {d.bet} 🪙"
    d.accepted, d.created = True, time.time()
    return ""


async def roll(chat_id: int, user_id: int, value: int) -> tuple[str, Duel | None]:
    """Кубик от участника. Возвращает ('wait'|'tie'|'done'|'', дуэль). Чужие кубики игнорируются."""
    d = active_duel(chat_id)
    if not d or not d.accepted or user_id not in (d.a, d.b) or user_id in d.rolls:
        return "", None
    if user_id == d.b and d.a not in d.rolls:
        return "", None   # первым кидает тот, кто вызвал
    d.rolls[user_id] = value
    d.created = time.time()   # пока кидают, игра не протухает
    if len(d.rolls) < 2:
        return "wait", d
    if d.rolls[d.a] == d.rolls[d.b]:
        d.rolls.clear()
        return "tie", d
    winner = d.a if d.rolls[d.a] > d.rolls[d.b] else d.b
    await store.add_coins(winner, d.bet * 2)
    DUELS.pop(chat_id, None)
    return "done", d


async def give_up(chat_id: int, user_id: int) -> tuple[str, Duel | None]:
    """Сдаться. До принятия: вызов просто отменяется. После: банк забирает соперник."""
    d = active_duel(chat_id)
    if not d or user_id not in (d.a, d.b):
        return "", None
    DUELS.pop(chat_id, None)
    if not d.accepted:
        return "cancel", d
    await store.add_coins(d.b if user_id == d.a else d.a, d.bet * 2)
    return "lost", d


async def refund_expired() -> list[Duel]:
    """Возвращает ставки, если игру в кости бросили посередине."""
    gone = []
    for chat_id, d in list(DUELS.items()):
        if time.time() - d.created > DUEL_TIMEOUT:
            DUELS.pop(chat_id, None)
            if d.accepted:
                await store.add_coins(d.a, d.bet)
                await store.add_coins(d.b, d.bet)
            gone.append(d)
    return gone


async def cancel_duel_of(chat_id: int, user_id: int) -> Duel | None:
    """Модерация убрала игрока (бан, мут, кик): игра в кости отменяется, принятые ставки возвращаются обоим."""
    d = active_duel(chat_id)
    if not d or user_id not in (d.a, d.b):
        return None
    DUELS.pop(chat_id, None)
    if d.accepted:
        await store.add_coins(d.a, d.bet)
        await store.add_coins(d.b, d.bet)
    return d
