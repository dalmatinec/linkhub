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
        assert h.labels(USER) == [["💎 Премиум", "🔥 Топ"], ["Алматы", "Астана"], ["Шымкент", "🌍 Другие города"],
                                  ["🔍 Поиск", "⭐ Избранное"], ["☰ Ещё"]], "города прямо на главном экране"
        assert h.find(USER, "Премиум").style == "primary"
        assert "—" not in scr.text and "«" not in scr.text

        await h.press(USER, "Другие города")
        assert h.screen(USER).id == scr.id, "экран редактируется, а не шлётся заново"
        assert "нет магазинов" in h.screen(USER).text, "по умолчанию сразу список магазинов"
        assert h.labels(USER) == [["◀️ Назад"]], "никакого списка городов"
        await h.press(USER, "Назад")
        await h.press(USER, "Шымкент")
        assert "Шымкент" in h.screen(USER).text and "нет магазинов" in h.screen(USER).text
        await h.press(USER, "Назад")
        await h.press(USER, "Ещё")
        assert h.labels(USER) == [["📝 Разместить магазин"], ["🌐 Язык"], ["◀️ Назад"]]

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
    await h.click(OWNER, f"x:scat:{shop_id}:1")  # категория VPN
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
        assert "🏙 <b>Города:</b> Алматы" in card.text, "города в карточке строятся сами"
        write = h.find(USER, "Написать").url
        assert write.startswith("https://t.me/gift_manager?text=") and "%D0%9A%D1%80%D1%83%D0%B8%D0%B7" in write, \
            "в чате с оператором уже вписано приветствие"
        assert h.labels(USER) == [["💬 Написать"], ["Канал"], ["⭐ В избранное", "📤 Поделиться"],
                                  ["🚩 Пожаловаться"], ["◀️ Назад"]]
        share_url = h.find(USER, "Поделиться").url
        assert share_url.startswith("https://t.me/share/url?url=") and f"start%3Dshop_{shop_id}" in share_url
        from aiogram.methods import SendMessage
        sent = [c for c in h.tg.calls if isinstance(c, SendMessage) and c.chat_id == USER]
        assert sent and all(c.protect_content is True for c in sent), "пересылка сообщений бота запрещена"
        owner_sent = [c for c in h.tg.calls if isinstance(c, SendMessage) and c.chat_id == OWNER]
        assert owner_sent and not any(c.protect_content is True for c in owner_sent), "админ может делать скриншоты"
        await h.press(USER, "Назад")
        assert h.labels(USER)[0] == ["Gift Shop"]

        await h.press(USER, "Назад")
        await h.press(USER, "Алматы")
        assert h.labels(USER)[0] == ["Gift Shop"], "магазинов мало — сразу список, без категорий"
        await h.app.db.execute("UPDATE settings SET value = '0' WHERE key = 'city_categories_min'")
        await h.app.catalog.reload()
        await h.press(USER, "Назад")
        await h.press(USER, "Алматы")
        assert h.labels(USER)[0] == ["🔐 VPN", "📋 Все магазины"], "в городе сначала категории"
        await h.press(USER, "VPN")
        assert "VPN" in h.screen(USER).text and h.labels(USER)[0] == ["Gift Shop"]
        await h.press(USER, "Gift Shop")
        await h.press(USER, "Назад")
        assert h.labels(USER)[0] == ["Gift Shop"], "назад из карточки — в ту же категорию"
        await h.press(USER, "Назад")
        await h.press(USER, "Все магазины")
        assert h.labels(USER)[0] == ["Gift Shop"]
        await h.click(OWNER, "x:cattog")  # категории в городе выключены — сразу магазины
        await h.click(USER, f"y:{next(c.id for c in h.app.catalog.cities.values() if c.label == 'Алматы')}:"
                            f"{next(i.id for i in h.app.catalog.menu.values() if i.kind == 'city_block')}:0")
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
        await h.press(USER, "Другие города")
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
        assert any("срок истёк" in (m.text or "").lower() for m in h.tg.chat(OWNER))

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
        await h.click(OWNER, f"x:irow:{item_id}:-1")  # один в ряду → приклеился к «Разместить магазин»
        await h.click(OWNER, f"x:irow:{item_id}:-1")  # не один → оторвался в свой ряд над ним
        await h.click(OWNER, f"x:irow:{item_id}:-1")  # один → приклеился к «Поиску»
        await h.send(USER, "/start")
        assert h.labels(USER)[3] == [search.label, "⭐ Избранное", "📢 Наш канал"]
        assert h.find(USER, "Наш канал").url == "https://t.me/our_channel"
        await h.click(OWNER, f"x:isolo:{item_id}")
        await h.click(OWNER, f"x:iact:{search.id}")
        await h.send(USER, "/start")
        assert ["📢 Наш канал"] in h.labels(USER) and all("Поиск" not in b for r in h.labels(USER) for b in r)
        await h.click(OWNER, "a:log:0")
        log_text = h.screen(OWNER).text
        assert "добавил кнопку меню" in log_text and "item." not in log_text, "журнал по-русски"
        await h.click(OWNER, "a:text:city_shops")
        assert "{город}" in h.screen(OWNER).text and "city_shops" not in h.screen(OWNER).text
        await h.stop()
    run(scenario())


def test_favorites(tmp_path):
    async def scenario():
        h = await Harness(tmp_path).start()
        shop_id = await make_shop(h)
        await h.send(USER, f"/start shop_{shop_id}")
        await h.press(USER, "В избранное")
        assert h.find(USER, "Из избранного")
        await h.send(USER, "/start")
        await h.press(USER, "Избранное")
        assert h.labels(USER)[0] == ["Gift Shop"]
        await h.press(USER, "Gift Shop")
        await h.press(USER, "Из избранного")
        await h.press(USER, "Назад")
        assert "Пока пусто" in h.screen(USER).text
    run(scenario())


def test_application_flow(tmp_path):
    async def scenario():
        h = await Harness(tmp_path).start()
        await h.send(USER, "/start")
        await h.press(USER, "Ещё")
        await h.press(USER, "Разместить магазин")
        await h.press(USER, "Заполнить заявку")
        assert "Шаг 1 из 6" in h.screen(USER).text
        await h.send(USER, "Star Shop")
        await h.send(USER, None, photo=[{"file_id": "p", "file_unique_id": "p", "width": 1, "height": 1}])
        assert "другой ответ" in h.screen(USER).text, "на текстовый вопрос фото не принимается"
        await h.send(USER, "Продаём звёзды и подарки")
        await h.press(USER, "Пропустить")  # прайс
        await h.send(USER, "@star_seller\nhttps://t.me/star_channel")
        await h.send(USER, "Алматы, Астана")
        h.tg.download_data = b"logo"
        await h.send(USER, None, photo=[{"file_id": "logo", "file_unique_id": "l", "width": 1, "height": 1}])
        assert "Проверьте заявку" in h.screen(USER).text and "Star Shop" in h.screen(USER).text
        assert len(h.tg.chat(USER)) == 1, "ответы удаляются, экран один"
        await h.press(USER, "Отправить")
        app_id = await h.app.db.fetchval("SELECT id FROM applications")
        assert app_id and any("Новая заявка" in (m.text or "") for m in h.tg.chat(OWNER))

        await h.send(USER, "/start")
        await h.press(USER, "Ещё")
        await h.press(USER, "Разместить магазин")
        assert "уже на проверке" in h.screen(USER).text

        await h.send(OWNER, "/admin")
        await h.click(OWNER, f"a:appl:{app_id}")
        assert "Star Shop" in h.screen(OWNER).text
        await h.click(OWNER, f"x:aplok:{app_id}")
        shop = next(s for s in h.app.catalog.shops.values() if s.label == "Star Shop")
        assert not shop.is_active and shop.media_id
        assert [c.url for c in shop.contacts] == ["https://t.me/star_seller", "https://t.me/star_channel"]
        assert {h.app.catalog.cities[c].label for c in shop.cities} == {"Алматы", "Астана"}
        assert any("одобрена" in (m.text or "") for m in h.tg.chat(USER)), "автору пришло уведомление"
    run(scenario())


def test_languages_and_translation_file(tmp_path):
    async def scenario():
        h = await Harness(tmp_path).start()
        KK = 55
        await h.feed(message={"message_id": 1, "date": 0, "chat": {"id": KK, "type": "private"},
                              "from": {**h._user(KK), "language_code": "kk"}, "text": "/start",
                              "entities": [{"type": "bot_command", "offset": 0, "length": 6}]})
        assert h.app.langs[KK] == "kk"
        assert "Добро пожаловать" in h.screen(KK).text, "нет перевода — показывается русский"

        await h.send(OWNER, "/admin")
        await h.click(OWNER, "x:tred:btn:back:label:kk")
        await h.send(OWNER, "◀️ Артқа")
        root = h.app.catalog.root_id
        await h.click(OWNER, "x:tred:item:%d:html:kk" % root)
        await h.send(OWNER, "Қош келдіңіз, {имя}!")
        await h.send(KK, "/start")
        assert h.screen(KK).text == "Қош келдіңіз, U55!"
        await h.press(KK, "Другие города")
        assert h.find(KK, "Артқа")

        # файл: выгрузка → перевод → загрузка
        await h.click(OWNER, "x:trexp:todo")
        exported = h.tg.documents[-1].decode()
        assert "=== text/other_cities/html" in exported and "kk: \n" in exported
        other = "ru: 🌍 <b>Другие города</b>\nВыберите магазин, город указан в карточке:\nkk: "
        assert other in exported
        filled = exported.replace(other, other + "🌍 <b>Басқа қалалар</b>")
        filled = filled.replace("ru: Здесь пока нет магазинов. Загляните позже.\nkk: ",
                                "ru: Здесь пока нет магазинов. Загляните позже.\nkk: <b>Бос")  # битый HTML
        h.tg.download_data = filled.encode()
        await h.click(OWNER, "x:trimp")
        await h.send(OWNER, None, document={"file_id": "tr", "file_unique_id": "tr", "file_name": "t.txt",
                                            "file_size": len(filled)})
        assert "Загружено переводов: 3" in h.screen(OWNER).text and "не закрыт" in h.screen(OWNER).text
        await h.send(KK, "/start")
        await h.press(KK, "Другие города")
        assert "Басқа қалалар" in h.screen(KK).text

        # русский поменяли — перевод помечен устаревшим
        await h.click(OWNER, "x:htm:text:cities")
        await h.send(OWNER, "🏙 Город?")
        await h.click(OWNER, "a:trl:text:cities")
        assert "⚠️" in h.screen(OWNER).text

        # ручной выбор языка
        await h.press(KK, "Артқа")
        await h.click(KK, f"L:en")
        assert h.app.langs[KK] == "en"
    run(scenario())


def test_broadcast_forward_and_log_channel(tmp_path):
    async def scenario():
        h = await Harness(tmp_path).start()
        await h.send(USER, "/start")
        await h.send(OWNER, "/admin")
        await h.click(OWNER, "x:logchat")
        await h.send(OWNER, "-100777")
        assert h.app.log_chat == -100777
        assert any("Канал подключён" in (m.text or "") for m in h.tg.chat(-100777))

        await h.click(OWNER, "x:bcnew")
        msg_id = await h.send(OWNER, "Новости!")
        await h.click(OWNER, f"a:bcc:{msg_id}:fwd:all")
        assert "Пересылкой" in h.screen(OWNER).text
        await h.click(OWNER, f"x:bcgo:{msg_id}:fwd:all")
        from bot.handlers.admin import people
        await people.broadcast_task
        assert any(m.text == "forward" for m in h.tg.chat(USER))
        assert any("Рассылка завершена" in (m.text or "") for m in h.tg.chat(-100777)), "отчёт в канал логов"
        assert any("рассылку" in (m.text or "") for m in h.tg.chat(-100777)), "действие админа в канал логов"
    run(scenario())


def test_upgrade_from_first_version(tmp_path):
    """База первой версии обновляется миграцией: данные на месте, новые таблицы и категории появились."""
    async def scenario():
        import aiosqlite
        from bot.db import MIGRATIONS
        async with aiosqlite.connect(tmp_path / "bot.db") as conn:
            await conn.executescript(f"BEGIN;{MIGRATIONS[0]}\nPRAGMA user_version=1;COMMIT;")
            await conn.execute("INSERT INTO shops(label, created_at, updated_at) VALUES ('Old Shop', 0, 0)")
            await conn.commit()
        h = await Harness(tmp_path).start()
        assert await h.app.db.fetchval("PRAGMA user_version") == len(MIGRATIONS)
        assert any(s.label == "Old Shop" for s in h.app.catalog.shops.values())
        assert len(h.app.catalog.categories) == 5 and len(h.app.catalog.fields) == 6
    run(scenario())


def test_errors_go_to_log_channel(tmp_path):
    async def scenario():
        from bot.telelog import TelegramLogHandler
        h = await Harness(tmp_path).start()
        await h.app.db.execute("INSERT OR REPLACE INTO settings(key, value) VALUES ('log_chat_id', '-100500')")
        await h.app.catalog.reload()
        handler = TelegramLogHandler(h.app)
        task = asyncio.create_task(handler.run())
        try:
            raise ValueError("сломалось")
        except ValueError:
            handler.emit(logging.LogRecord("bot.test", logging.ERROR, __file__, 1, "Упало", None,
                                           __import__("sys").exc_info()))
        await asyncio.sleep(0.05)
        task.cancel()
        text = h.tg.chat(-100500)[-1].text
        assert "Ошибка" in text and "ValueError" in text
    run(scenario())


def test_row_arrows_move_one_step(tmp_path):
    """Две кнопки в ряду: «вниз» сначала отрывает кнопку в свой ряд, второе «вниз» — к следующему ряду.
    Блок городов кнопка перепрыгивает целиком."""
    async def scenario():
        h = await Harness(tmp_path).start()
        top = next(i for i in h.app.catalog.menu.values() if i.label == "🔥 Топ")
        root = h.app.catalog.root_id
        await h.send(OWNER, "/admin")
        await h.click(OWNER, f"a:arr:{root}:{top.id}")
        assert "👉 🔥 Топ" in str(h.labels(OWNER))
        await h.click(OWNER, f"x:arrmv:{root}:{top.id}:D")
        await h.send(USER, "/start")
        assert h.labels(USER)[:3] == [["💎 Премиум"], ["🔥 Топ"], ["Алматы", "Астана"]]
        await h.click(OWNER, f"x:arrmv:{root}:{top.id}:D")  # перепрыгнула города
        await h.send(USER, "/start")
        assert h.labels(USER)[:4] == [["💎 Премиум"], ["Алматы", "Астана"], ["Шымкент", "🌍 Другие города"], ["🔥 Топ"]]
        await h.click(OWNER, f"x:arrmv:{root}:{top.id}:D")  # приклеилась к «Поиску»
        await h.send(USER, "/start")
        assert h.labels(USER)[3] == ["🔥 Топ", "🔍 Поиск", "⭐ Избранное"]
        await h.click(OWNER, f"x:arrmv:{root}:{top.id}:R")
        await h.send(USER, "/start")
        assert h.labels(USER)[3] == ["🔍 Поиск", "🔥 Топ", "⭐ Избранное"]
        for _ in range(3):  # отрыв от ряда → через блок городов → к «Премиуму»
            await h.click(OWNER, f"x:arrmv:{root}:{top.id}:U")
        await h.send(USER, "/start")
        assert h.labels(USER)[0] == ["💎 Премиум", "🔥 Топ"], "вернулась наверх"
    run(scenario())

def test_video_as_gif_autoplay(tmp_path):
    async def scenario():
        from aiogram.methods import SendAnimation
        h = await Harness(tmp_path).start()
        root = h.app.catalog.root_id
        h.tg.download_data = b"mp4"
        await h.send(OWNER, "/admin")
        await h.click(OWNER, f"x:med:item:{root}")
        await h.send(OWNER, None, video={"file_id": "v", "file_unique_id": "v", "width": 1, "height": 1,
                                         "duration": 3, "mime_type": "video/mp4"})
        await h.click(OWNER, f"a:imore:{root}")  # редкие действия — на экране «Ещё»
        assert "Сделать GIF" in str(h.labels(OWNER))
        await h.click(OWNER, f"x:mkind:item:{root}")
        assert "Теперь это GIF" in h.screen(OWNER).text
        await h.send(USER, "/start")
        sent = [c for c in h.tg.calls if isinstance(c, SendAnimation)]
        assert sent and isinstance(sent[-1].animation, FSInputFile), "перезалито как GIF"
        assert h.screen(USER).kind == "animation"
    run(scenario())


def test_smart_search(tmp_path):
    async def scenario():
        h = await Harness(tmp_path).start()
        gift = await make_shop(h, "Gift Shop")  # Алматы, VPN, «Подарки Telegram и VPN»
        await h.click(OWNER, f"x:htm:shop:{gift}")
        await h.send(OWNER, "Подарки Telegram от 1500 тг и VPN 2000₸")
        star = await make_shop(h, "Star Market")
        await h.click(OWNER, f"x:htm:shop:{star}")
        await h.send(OWNER, "Звёзды Telegram по 500 тг")
        astana = next(c.id for c in h.app.catalog.cities.values() if c.label == "Астана")
        almaty = next(c.id for c in h.app.catalog.cities.values() if c.label == "Алматы")
        await h.click(OWNER, f"x:sct:{star}:{almaty}:0")  # убрать Алматы
        await h.click(OWNER, f"x:sct:{star}:{astana}:0")
        await h.click(OWNER, f"x:scat:{star}:1")  # убрать VPN

        from bot import search
        cat = h.app.catalog
        names = lambda q: [s.label for s in search.run(cat, q)[0]]  # noqa: E731
        assert names("vpn алматы") == ["Gift Shop"]
        assert names("в астане") == ["Star Market"]
        assert names("vpn астана") == []
        assert names("до 1000") == ["Star Market"], "цена из текста карточки"
        assert set(names("telegram 3000")) == {"Gift Shop", "Star Market"}, "просто число — бюджет"
        assert names("подарков") == ["Gift Shop"], "по основе слова"
        assert names("звезды") == ["Star Market"], "ё = е"
        assert names("gift") == ["Gift Shop"]
        assert set(names("премиум")) == {"Gift Shop", "Star Market"}, "метка как фильтр"

        await h.send(USER, "/start")
        await h.press(USER, "Поиск")
        await h.send(USER, "vpn алматы до 5000")
        text = h.screen(USER).text
        assert "Алматы" in text and "≤ 5000" in text and h.labels(USER)[0] == ["Gift Shop"]
    run(scenario())


def test_new_tag_menu_button(tmp_path):
    async def scenario():
        h = await Harness(tmp_path).start()
        shop_id = await make_shop(h)
        await h.click(OWNER, "x:tnew")
        await h.send(OWNER, "Новинки")
        tag_id = max(h.app.catalog.tags)
        await h.click(OWNER, f"x:tagbtn:{tag_id}")
        await h.click(OWNER, f"x:stt:{shop_id}:{tag_id}")
        await h.send(USER, "/start")
        await h.press(USER, "Новинки")
        assert h.labels(USER)[0] == ["Gift Shop"], "метку дали — магазин сам в подборке"
    run(scenario())


def test_existing_install_gets_new_layout_and_texts(tmp_path):
    """База со старым меню: «Выбрать город» становится блоком городов, «Разместить» и «Язык» уходят в «Ещё»,
    стандартные тексты обновляются, а свои правки админа остаются."""
    async def scenario():
        h = await Harness(tmp_path).start()
        db = h.app.db
        root = h.app.catalog.root_id
        more = next(i for i in h.app.catalog.menu.values() if i.label == "☰ Ещё")
        # делаем «как было»: старые тексты, старое меню, без флагов обновления
        await db.execute("UPDATE menu_items SET kind = 'cities', label = '🏙 Выбрать город' WHERE kind = 'city_block'")
        await db.execute("UPDATE menu_items SET parent_id = ?, row = 4 WHERE parent_id = ?", (root, more.id))
        await db.execute("DELETE FROM menu_items WHERE id = ?", (more.id,))
        await db.execute("UPDATE texts SET html = 'Здесь пока пусто.' WHERE key = 'empty'")
        await db.execute("UPDATE texts SET html = 'Мой текст — с тире' WHERE key = 'flood'")
        await db.execute("UPDATE menu_items SET html = 'Моё приветствие про Cruise' WHERE id = ?", (root,))
        await db.execute("DELETE FROM settings WHERE key IN ('layout_v2', 'texts_v3')")
        await h.stop()

        h2 = await Harness(tmp_path).start()
        cat = h2.app.catalog
        assert cat.text("empty").html == "Здесь пока нет магазинов. Загляните позже.", "стандартный текст обновлён"
        assert cat.text("flood").html == "Мой текст — с тире", "свой текст не тронут"
        assert cat.menu[cat.root_id].html == "Моё приветствие про Cruise"
        await h2.send(USER, "/start")
        assert h2.labels(USER)[1] == ["Алматы", "Астана"] and h2.labels(USER)[-1] == ["☰ Ещё"]
        await h2.press(USER, "Ещё")
        assert h2.labels(USER)[:2] == [["📝 Разместить магазин"], ["🌐 Язык"]]
    run(scenario())


def test_other_cities_list_shops(tmp_path):
    async def scenario():
        h = await Harness(tmp_path).start()
        shop_id = await make_shop(h)  # Алматы
        await h.click(OWNER, f"x:scnew:{shop_id}")
        await h.send(OWNER, "Экибастуз\nКараганда")
        cat = h.app.catalog
        names = {cat.cities[c].label for c in cat.shops[shop_id].cities}
        assert names == {"Алматы", "Экибастуз", "Караганда"}, "новый город создан, существующий найден"
        assert sum(1 for c in cat.cities.values() if c.label == "Караганда") == 1
        await h.send(USER, "/start")
        await h.press(USER, "Другие города")
        assert h.labels(USER)[0] == ["Gift Shop"]
        await h.press(USER, "Gift Shop")
        assert "Алматы" in h.screen(USER).text and "Экибастуз" in h.screen(USER).text
        await h.press(USER, "Назад")
        assert h.labels(USER)[0] == ["Gift Shop"], "назад из карточки в Другие города"
    run(scenario())


def test_operator_button_easy_change(tmp_path):
    """У продавца несколько кнопок связи, каждая меняется прямо с экрана магазина."""
    async def scenario():
        h = await Harness(tmp_path).start()
        shop_id = await make_shop(h)  # «💬 Написать | @gift_manager», «Канал | t.me/gifts»
        await h.click(OWNER, f"a:shop:{shop_id}")
        assert h.find(OWNER, "💬 Написать → @gift_manager") and h.find(OWNER, "Канал → @gifts")
        await h.press(OWNER, "Написать → @gift_manager")
        await h.press(OWNER, "Сменить контакт")
        await h.send(OWNER, "@new_seller")
        await h.click(OWNER, f"a:shop:{shop_id}")
        await h.press(OWNER, "Добавить контакт")
        await h.send(OWNER, "@second_seller")
        urls = [c.url for c in h.app.catalog.shops[shop_id].contacts]
        assert urls == ["https://t.me/new_seller", "https://t.me/gifts", "https://t.me/second_seller"]
        await h.press(OWNER, "Канал → @gifts")
        await h.press(OWNER, "Удалить кнопку")
        assert len(h.app.catalog.shops[shop_id].contacts) == 2
        await h.send(USER, f"/start shop_{shop_id}")
        assert h.labels(USER)[:2] == [["💬 Написать"], ["💬 Написать оператору"]]
        assert h.find(USER, "💬 Написать").url.startswith("https://t.me/new_seller?text=")
    run(scenario())


def test_admin_menu_shows_city_buttons(tmp_path):
    """В админке города в меню выглядят как обычные кнопки и настраиваются как обычные кнопки."""
    async def scenario():
        h = await Harness(tmp_path).start()
        root = h.app.catalog.root_id
        await h.send(OWNER, "/admin")
        await h.click(OWNER, f"a:item:{root}")
        labels = h.labels(OWNER)
        assert ["Алматы", "Астана"] in labels and ["Шымкент", "🌍 Другие города"] in labels
        assert not any("[города]" in x for r in labels for x in r)
        await h.press(OWNER, "Астана")
        assert "Астана" in h.screen(OWNER).text and h.find(OWNER, "Текст и иконка")
        await h.click(OWNER, f"a:item:{root}")
        await h.press(OWNER, "Другие города")
        assert h.find(OWNER, "Текст и иконка") and h.find(OWNER, "Цвет")
    run(scenario())


def test_admin_home_is_short(tmp_path):
    async def scenario():
        h = await Harness(tmp_path).start()
        await h.send(OWNER, "/admin")
        assert h.labels(OWNER) == [["🏪 Магазины", "📝 Заявки"], ["📣 Рассылка", "🚩 Жалобы"],
                                   ["📊 Статистика", "👥 Пользователи"], ["⚙️ Настройки каталога"]]
        await h.press(OWNER, "Настройки каталога")
        await h.press(OWNER, "Города")
        await h.press(OWNER, "Назад")
        assert "Настройки каталога" in h.screen(OWNER).text, "назад из раздела настроек ведёт в настройки"
        await h.press(OWNER, "Меню")
        assert "Главное меню" in h.screen(OWNER).text
    run(scenario())


def test_texts_grouped_by_topic(tmp_path):
    async def scenario():
        h = await Harness(tmp_path).start()
        await h.send(OWNER, "/admin")
        await h.click(OWNER, "a:texts")
        assert len(h.labels(OWNER)) <= 7, "тем немного, а не 50 пунктов"
        await h.press(OWNER, "Карточка магазина")
        assert h.find(OWNER, "Приветствие оператору") and h.find(OWNER, "🔘 ⭐ В избранное")
        await h.press(OWNER, "Приветствие оператору")
        await h.press(OWNER, "Назад")
        assert "Карточка магазина" in h.screen(OWNER).text, "назад ведёт в ту же тему"
    run(scenario())
