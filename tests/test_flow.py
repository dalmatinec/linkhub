"""Сквозные тесты: бот целиком на фейковом Telegram API.
Запуск: python -m pytest -q"""
import asyncio
import itertools
import logging
from pathlib import Path

import pytest
from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.methods import AnswerCallbackQuery, SendPhoto
from aiogram.types import FSInputFile, Update

from bot.__main__ import setup
from bot.backup import make_backup, restore_backup
from bot.catalog import now
from bot.config import Config
from bot.handlers.admin import router as admin_router
from bot.handlers.user import router as user_router
from bot.jobs import check_tag_expiry

from .fake_telegram import FakeTelegram

OWNER, USER = 1, 42
_ids = itertools.count(1)
_open: list["Harness"] = []


class Harness:
    def __init__(self, tmp: Path, bot_id: int = 1000) -> None:
        self.tmp = tmp
        self.tg = FakeTelegram(bot_id=bot_id)
        self.bot = Bot(f"{bot_id}:TEST", session=self.tg,
                       default=DefaultBotProperties(parse_mode="HTML", link_preview_is_disabled=True))
        self.config = Config(bot_token="x", owner_ids=frozenset({OWNER}), data_dir=tmp, log_level="INFO")

    async def start(self, flood: bool = False) -> "Harness":
        for router in (admin_router, user_router):  # роутеры — модульные синглтоны, отвязываем от прошлого теста
            router._parent_router = None
        self.app, self.dp, self.guard = await setup(self.config, self.bot)
        _open.append(self)
        if not flood:  # тесты жмут кнопки быстрее человека
            await self.app.db.execute("UPDATE settings SET value = '0' WHERE key = 'flood_limit'")
            await self.app.catalog.reload()
        return self

    async def stop(self) -> None:
        if self in _open:
            _open.remove(self)
        await self.app.flush()
        await self.app.db.close()

    async def feed(self, **update) -> None:
        await self.dp.feed_update(self.bot, Update.model_validate({"update_id": next(_ids), **update},
                                                                   context={"bot": self.bot}))

    def _user(self, uid: int) -> dict:
        return {"id": uid, "is_bot": False, "first_name": f"U{uid}", "username": f"user{uid}"}

    async def send(self, uid: int, text: str | None = None, entities: list | None = None, **extra) -> int:
        """Сообщение пользователя. Кладём его в «чат», чтобы бот мог его удалить."""
        from .fake_telegram import ChatMessage
        mid = next(self.tg._ids)
        self.tg.messages[(uid, mid)] = ChatMessage(mid, uid, text, None, "text", None)
        msg = {"message_id": mid, "date": 0, "chat": {"id": uid, "type": "private"}, "from": self._user(uid), **extra}
        if text is not None:
            msg["text"] = text
        if entities:
            msg["entities"] = entities
        if text and text.startswith("/"):
            msg["entities"] = [{"type": "bot_command", "offset": 0, "length": len(text.split()[0])}]
        await self.feed(message=msg)
        return mid

    async def click(self, uid: int, data: str, message_id: int | None = None) -> None:
        m = self.tg.messages[(uid, message_id)] if message_id else self.screen(uid)
        await self.feed(callback_query={
            "id": str(next(_ids)), "from": self._user(uid), "chat_instance": "c", "data": data,
            "message": self.tg.msg(self.bot, m).model_dump(by_alias=True, exclude_none=True),
        })

    def screen(self, uid: int):
        return self.tg.last(uid)

    def buttons(self, uid: int) -> list[list]:
        m = self.screen(uid)
        return m.markup.inline_keyboard if m.markup else []

    def labels(self, uid: int) -> list[list[str]]:
        return [[b.text for b in row] for row in self.buttons(uid)]

    def find(self, uid: int, text: str):
        for row in self.buttons(uid):
            for b in row:
                if text in b.text:
                    return b
        raise AssertionError(f"нет кнопки {text!r} в {self.labels(uid)}")

    async def press(self, uid: int, text: str) -> None:
        await self.click(uid, self.find(uid, text).callback_data)


def run(coro):
    async def wrapper():
        try:
            return await coro
        finally:  # незакрытая база держит поток aiosqlite и не даёт процессу завершиться
            for h in list(_open):
                await h.stop()
    return asyncio.run(wrapper())


@pytest.fixture(autouse=True)
def no_unhandled_errors(caplog):
    caplog.set_level(logging.WARNING)
    yield
    errors = [r for r in caplog.records if r.levelno >= logging.ERROR and "Медиа" not in r.getMessage()]
    assert not errors, [r.getMessage() for r in errors]


def test_user_navigation(tmp_path):
    async def scenario():
        h = await Harness(tmp_path).start()
        start_id = await h.send(USER, "/start")
        assert (USER, start_id) not in h.tg.messages, "/start пользователя удаляется"
        scr = h.screen(USER)
        assert "Добро пожаловать, U42" in scr.text
        assert h.labels(USER) == [["💎 Премиум", "🔥 Топы"], ["🏙 Выбрать город"], ["🔍 Поиск"]]
        assert h.find(USER, "Премиум").style == "primary"

        await h.press(USER, "Выбрать город")
        assert h.screen(USER).id == scr.id, "экран редактируется, а не шлётся заново"
        assert h.labels(USER) == [["Алматы", "Астана"], ["Шымкент", "🌍 Другие города"], ["◀️ Назад"]]

        await h.press(USER, "Другие города")
        labels = h.labels(USER)
        assert all(len(r) == 2 for r in labels[:5]) and labels[5] == ["1/2", "▶️"] and labels[6] == ["◀️ Назад"]
        await h.press(USER, "▶️")
        assert h.labels(USER)[-2] == ["◀️", "2/2"]
        await h.press(USER, "Уральск")
        assert "Уральск" in h.screen(USER).text and "пусто" in h.screen(USER).text
        await h.press(USER, "Назад")
        assert h.labels(USER)[-2] == ["◀️", "2/2"], "назад возвращает на ту же страницу городов"

        await h.send(USER, "/start")
        assert len(h.tg.chat(USER)) == 1, "в чате всегда один экран"
        await h.send(USER, "привет")
        assert len(h.tg.chat(USER)) == 1, "мусорные сообщения удаляются"
        await h.stop()
    run(scenario())


async def make_shop(h: Harness, name: str = "Gift Shop") -> int:
    await h.send(OWNER, "/admin")
    await h.press(OWNER, "Магазины")
    await h.press(OWNER, "Добавить")
    await h.send(OWNER, name)
    shop_id = max(h.app.catalog.shops)
    assert not h.app.catalog.shops[shop_id].is_active
    await h.click(OWNER, f"x:htm:shop:{shop_id}")
    await h.send(OWNER, "Подарки Telegram и VPN", entities=[{"type": "bold", "offset": 0, "length": 7}])
    await h.click(OWNER, f"x:stt:{shop_id}:1")  # Премиум
    almaty = next(c.id for c in h.app.catalog.cities.values() if c.label == "Алматы")
    await h.click(OWNER, f"a:scity:{shop_id}:0")
    await h.click(OWNER, f"x:sct:{shop_id}:{almaty}:0")
    await h.click(OWNER, f"x:cset:{shop_id}")
    await h.send(OWNER, "💬 Написать | @gift_manager\nКанал | t.me/gifts")
    await h.click(OWNER, f"x:sact:{shop_id}")
    return shop_id


def test_admin_creates_shop_and_user_sees_it(tmp_path):
    async def scenario():
        h = await Harness(tmp_path).start()
        shop_id = await make_shop(h)
        shop = h.app.catalog.shops[shop_id]
        assert shop.is_active and shop.html == "<b>Подарки</b> Telegram и VPN"
        assert [c.url for c in shop.contacts] == ["https://t.me/gift_manager", "https://t.me/gifts"]
        assert len(h.tg.chat(OWNER)) == 1, "ввод админа удаляется, экран админки один"

        await h.send(USER, "/start")
        await h.press(USER, "Премиум")
        assert h.labels(USER)[0] == ["Gift Shop"]
        await h.press(USER, "Gift Shop")
        card = h.screen(USER)
        assert "<b>Подарки</b>" in card.text
        assert h.labels(USER) == [["💬 Написать"], ["Канал"], ["🚩 Пожаловаться"], ["◀️ Назад"]]
        await h.press(USER, "Назад")
        assert h.labels(USER)[0] == ["Gift Shop"]

        await h.press(USER, "Назад")
        await h.press(USER, "Выбрать город")
        await h.press(USER, "Алматы")
        assert h.labels(USER)[0] == ["Gift Shop"]

        # поиск
        await h.send(USER, "/start")
        await h.press(USER, "Поиск")
        await h.send(USER, "vpn")
        assert "vpn" in h.screen(USER).text and h.labels(USER)[0] == ["Gift Shop"]
        assert len(h.tg.chat(USER)) == 1

        # жалоба
        await h.press(USER, "Gift Shop")
        await h.press(USER, "Пожаловаться")
        await h.send(USER, "Не отвечают")
        assert await h.app.db.fetchval("SELECT COUNT(*) FROM reports") == 1
        assert any("Жалоба" in (m.text or "") for m in h.tg.chat(OWNER))

        # deep link
        await h.send(USER, f"/start shop_{shop_id}")
        assert "<b>Подарки</b>" in h.screen(USER).text
        await h.stop()
    run(scenario())


def test_label_with_premium_emoji_becomes_icon(tmp_path):
    async def scenario():
        h = await Harness(tmp_path).start()
        await h.send(OWNER, "/admin")
        await h.click(OWNER, "x:lbl:btn:back")
        await h.send(OWNER, "⭐ Вернуться", entities=[
            {"type": "custom_emoji", "offset": 0, "length": 1, "custom_emoji_id": "5368324170671202286"}])
        b = h.app.catalog.button("back")
        assert (b.label, b.icon) == ("Вернуться", "5368324170671202286")
        await h.click(OWNER, "x:sty:btn:back")
        assert h.app.catalog.button("back").style == "primary"

        await h.send(USER, "/start")
        await h.press(USER, "Выбрать город")
        back = h.find(USER, "Вернуться")
        assert back.icon_custom_emoji_id == "5368324170671202286" and back.style == "primary"
        await h.stop()
    run(scenario())


def test_media_survives_token_change(tmp_path):
    async def scenario():
        h = await Harness(tmp_path).start()
        shop_id = await make_shop(h)
        h.tg.download_data = b"\xff\xd8fake-jpeg"
        await h.click(OWNER, f"x:med:shop:{shop_id}")
        await h.send(OWNER, None, photo=[{"file_id": "incoming", "file_unique_id": "u", "width": 1, "height": 1,
                                          "file_size": 100}])
        media_id = h.app.catalog.shops[shop_id].media_id
        assert media_id and h.app.media.get(media_id).path.exists()

        await h.send(USER, f"/start shop_{shop_id}")
        assert h.screen(USER).kind == "photo" and h.tg.uploads == 0, "первый бот шлёт по file_id"
        await h.press(USER, "Назад")
        assert h.screen(USER).kind == "text" and len(h.tg.chat(USER)) == 1
        await h.stop()

        # новый токен = новый бот, те же данные
        h2 = await Harness(tmp_path, bot_id=2000).start()
        assert [m.id for m in h2.app.media.pending_warmup()] == [media_id]
        await h2.send(USER, f"/start shop_{shop_id}")
        sent = [c for c in h2.tg.calls if isinstance(c, SendPhoto)][-1]
        assert isinstance(sent.photo, FSInputFile), "новый бот заливает файл с диска"
        assert h2.app.media.file_ids[media_id].startswith("fid_")

        # битый file_id — перезаливка без ошибки
        h2.tg.bad_file_ids.add(h2.app.media.file_ids[media_id])
        await h2.send(USER, f"/start shop_{shop_id}")
        assert h2.screen(USER).kind == "photo" and h2.tg.uploads == 2

        # файл потерян и file_id нет — карточка без медиа, админ предупреждён
        h2.app.media.get(media_id).path.unlink()
        h2.tg.bad_file_ids.add(h2.app.media.file_ids[media_id])
        await h2.send(USER, f"/start shop_{shop_id}")
        assert h2.screen(USER).kind == "text" and "<b>Подарки</b>" in h2.screen(USER).text
        assert any("не найден на диске" in (m.text or "") for m in h2.tg.chat(OWNER))
        await h2.stop()
    run(scenario())


def test_flood_and_ban(tmp_path):
    async def scenario():
        h = await Harness(tmp_path).start(flood=True)
        await h.send(USER, "/start")
        root = h.app.catalog.root_id
        for _ in range(40):
            await h.click(USER, f"m:{root}")
        answers = [c for c in h.tg.calls if isinstance(c, AnswerCallbackQuery) and c.text]
        assert answers, "антифлуд отвечает"
        await asyncio.sleep(0.05)
        assert h.app.is_banned(USER), "после серии нарушений — автобан"

        await h.app.unban(USER)
        await h.send(OWNER, "/admin")
        await h.click(OWNER, f"x:ban:{USER}:0")
        assert h.app.is_banned(USER)
        await h.click(OWNER, f"x:ban:{OWNER}:0")
        assert not h.app.is_banned(OWNER), "владельца забанить нельзя"
        await h.stop()
    run(scenario())


def test_moderator_permissions(tmp_path):
    async def scenario():
        h = await Harness(tmp_path).start()
        await h.send(OWNER, "/admin")
        await h.click(OWNER, "x:adnew")
        await h.send(OWNER, "77")
        assert h.app.catalog.admins[77] == {"shops"}
        await h.send(77, "/admin")
        assert [r for r in h.labels(77)] == [["🏪 Магазины"]]
        await h.click(77, "a:users")
        assert "Нет доступа" in h.screen(77).text
        await h.stop()
    run(scenario())


def test_tag_expiry_and_backup_restore(tmp_path):
    async def scenario():
        h = await Harness(tmp_path).start()
        shop_id = await make_shop(h)
        await h.app.db.execute("UPDATE shop_tags SET expires_at = ? WHERE shop_id = ?", (now() - 1, shop_id))
        await check_tag_expiry(h.app)
        assert h.app.catalog.shops[shop_id].tags == {}
        assert any("срок истёк" in (m.text or "") for m in h.tg.chat(OWNER))

        path = await make_backup(h.app)
        await h.app.db.execute("DELETE FROM shops")
        await h.app.catalog.reload()
        assert not h.app.catalog.shops
        await restore_backup(h.app, path)
        assert shop_id in h.app.catalog.shops
        await h.stop()
    run(scenario())


def test_menu_editing(tmp_path):
    async def scenario():
        h = await Harness(tmp_path).start()
        root = h.app.catalog.root_id
        await h.send(OWNER, "/admin")
        await h.click(OWNER, f"x:inew:{root}:url")
        await h.send(OWNER, "📢 Наш канал")
        item_id = max(h.app.catalog.menu)
        await h.click(OWNER, f"x:iurl:{item_id}")
        await h.send(OWNER, "@our_channel")
        search = next(i for i in h.app.catalog.menu.values() if i.kind == "search")
        await h.click(OWNER, f"x:irow:{item_id}:-1")  # в ряд к «Поиску»
        await h.send(USER, "/start")
        assert h.labels(USER)[-1] == [search.label, "📢 Наш канал"]
        assert h.find(USER, "Наш канал").url == "https://t.me/our_channel"
        await h.click(OWNER, f"x:isolo:{item_id}")
        await h.click(OWNER, f"x:iact:{search.id}")
        await h.send(USER, "/start")
        assert h.labels(USER)[-1] == ["📢 Наш канал"] and ["🔍 Поиск"] not in h.labels(USER)
        await h.stop()
    run(scenario())
