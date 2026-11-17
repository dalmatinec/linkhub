"""Связь с модератором: API Бакси (127.0.0.1, X-Key), события, ники. python -m pytest -q"""

import asyncio
import time
from types import SimpleNamespace

import pytest
from aiohttp.test_utils import TestClient, TestServer

from bot import config, db
from bot.services import api, guardlink

KEY = "test-key"
CHAT = -1001234567890


class FakeBot:
    async def get_chat_administrators(self, chat_id):
        return [SimpleNamespace(user=SimpleNamespace(id=111)), SimpleNamespace(user=SimpleNamespace(id=777))]

    async def send_message(self, *a, **k):
        return SimpleNamespace(message_id=1, chat=SimpleNamespace(id=CHAT))


def run(tmp_path, monkeypatch, fn):
    monkeypatch.setattr(config, "BAXI_API_KEY", KEY)
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "bot.db")

    async def go():
        await db.connect()
        from bot.economy import store
        await store.init()
        await guardlink.init()
        c = TestClient(TestServer(api.make_app(FakeBot())))
        await c.start_server()
        try:
            return await fn(c)
        finally:
            await c.close()
            await db.close()
            db._db = None
    return asyncio.run(go())


H = {"X-Key": KEY}


def event(kind, **kw):
    return {"type": kind, "chat_id": CHAT, "user_id": 5, "by_id": 111, "until": 0, "reason": "", "warns": 0,
            "warn_limit": 3, "ts": int(time.time()), **kw}


def test_auth(tmp_path, monkeypatch):
    async def fn(c):
        assert (await c.get(f"/v1/chat/{CHAT}")).status == 401
        assert (await c.get(f"/v1/chat/{CHAT}", headers={"X-Key": "nope"})).status == 401
        assert (await c.post("/v1/events", json=event("warn"))).status == 401
        assert (await c.get("/v1/ping", headers=H)).status == 200
    run(tmp_path, monkeypatch, fn)


def test_chat_info_tariffs(tmp_path, monkeypatch):
    async def fn(c):
        data = await (await c.get(f"/v1/chat/{CHAT}", headers=H)).json()
        assert data["known"] is False and data["paid"] is False
        await db.ensure_chat(CHAT, "Тест")
        await db.update_chat(CHAT, approved=1, active=1, rent_until=time.time() + 86400, trial=0, free=0)
        data = await (await c.get(f"/v1/chat/{CHAT}", headers=H)).json()
        assert data["known"] and data["active"] and data["paid"] and not data["trial"] and data["until"] > 0
        await db.update_chat(CHAT, trial=1)
        data = await (await c.get(f"/v1/chat/{CHAT}", headers=H)).json()
        assert data["trial"] and not data["paid"]
        await db.update_chat(CHAT, trial=0, free=1)
        data = await (await c.get(f"/v1/chat/{CHAT}", headers=H)).json()
        assert data["free"] and not data["paid"] and not data["trial"]
        await db.update_chat(CHAT, free=0, rent_until=0)      # без срока: твои чаты считаются оплаченными
        data = await (await c.get(f"/v1/chat/{CHAT}", headers=H)).json()
        assert data["paid"]
        await db.update_chat(CHAT, rent_until=time.time() - 10)   # аренда кончилась
        data = await (await c.get(f"/v1/chat/{CHAT}", headers=H)).json()
        assert not data["paid"]
    run(tmp_path, monkeypatch, fn)


def test_trusted(tmp_path, monkeypatch):
    async def fn(c):
        await db.ensure_chat(CHAT, "Тест")
        await db.touch_user(CHAT, 42, "Вип", "vip")
        await db.set_perks(42, vip_until=time.time() + 3600)
        data = await (await c.get(f"/v1/chat/{CHAT}/trusted", headers=H)).json()
        assert data == {"admins": [111, 777], "vip": [42]}
    run(tmp_path, monkeypatch, fn)


def test_events_state_and_summary(tmp_path, monkeypatch):
    async def fn(c):
        await db.ensure_chat(CHAT, "Тест")
        r = await c.post("/v1/events", headers=H, json=event("warn", warns=2))
        assert (await r.json()) == {"ok": True}
        assert await guardlink.warns_line(CHAT, 5) == "⚠️ предупреждения 2/3"
        assert not await guardlink.is_blocked(CHAT, 5)
        await c.post("/v1/events", headers=H, json=event("mute", until=int(time.time()) + 3600, warns=0))
        assert await guardlink.is_blocked(CHAT, 5)
        assert await guardlink.warns_line(CHAT, 5) == ""   # на лимите модератор обнуляет
        await c.post("/v1/events", headers=H, json=event("unmute"))
        assert not await guardlink.is_blocked(CHAT, 5)
        await c.post("/v1/events", headers=H, json=event("ban", user_id=6))
        assert await guardlink.blocked_ids(CHAT) == {6}
        await c.post("/v1/events", headers=H, json=event("spam", user_id=7))
        counts = await guardlink.day_counts(CHAT, time.time() - 3600)
        assert counts == {"warn": 1, "mute": 1, "unmute": 1, "ban": 1, "spam": 1}
        assert guardlink.summary_line(counts) == ("🛡 <b>За день:</b> 1 мут, 1 предупреждение, 1 бан, "
                                                  "1 спам удалён")
        assert (await c.post("/v1/events", headers=H, json=event("hug"))).status == 400
        assert (await c.post("/v1/events", headers=H, data="не json")).status == 400
    run(tmp_path, monkeypatch, fn)


def test_ban_removes_from_games_and_lists(tmp_path, monkeypatch):
    async def fn(c):
        from bot.economy import service, store
        await db.ensure_chat(CHAT, "Тест")
        await db.call_add(CHAT, 5, "Вася")
        await store.wallet(5, "Вася")
        await store.wallet(9, "Петя")
        await store.add_coins(5, 500)
        await store.add_coins(9, 500)
        before = (await store.wallet(5))["coins"], (await store.wallet(9))["coins"]
        assert await service.start_duel(CHAT, 5, "Вася", 9, "Петя", 100) == ""
        assert await service.accept_duel(CHAT, 9) == ""
        await c.post("/v1/events", headers=H, json=event("ban"))
        assert service.active_duel(CHAT) is None
        assert ((await store.wallet(5))["coins"], (await store.wallet(9))["coins"]) == before   # ставки вернулись
        assert [r["user_id"] for r in await db.call_list(CHAT)] == []
    run(tmp_path, monkeypatch, fn)


def test_nicks(tmp_path, monkeypatch):
    async def fn(c):
        await db.ensure_chat(CHAT, "Тест")
        await db.touch_user(CHAT, 5, "Вася", "vasya")
        data = await (await c.get("/v1/user/5", headers=H)).json()
        assert data["name"] == "Вася" and data["nick"] == "" and data["nick_plain"] == "Вася"
        await db.set_perks(5, look_forever=1, nick="𝐁𝐚𝐤𝐬𝐢 ✨", emoji_alt="🔥", emoji_id="123")
        data = await (await c.get("/v1/user/5", headers=H)).json()
        assert data["nick"] == "𝐁𝐚𝐤𝐬𝐢 ✨" and data["nick_plain"] == "Baksi" and data["emoji_id"] == "123"
        data = await (await c.get("/v1/users?ids=5,6", headers=H)).json()
        assert set(data["users"]) == {"5", "6"} and data["users"]["6"]["name"] == ""
    run(tmp_path, monkeypatch, fn)


def test_tease_when_enabled(tmp_path, monkeypatch):
    said = []

    async def fake_in_character(bot, chat_id, situation, fallbacks, *a, **k):
        said.append((chat_id, situation, fallbacks))

    async def fn(c):
        from bot.services import talk
        monkeypatch.setattr(talk, "in_character", fake_in_character)
        monkeypatch.setattr(guardlink.random, "random", lambda: 0.0)
        guardlink._last_tease.clear()
        await db.ensure_chat(CHAT, "Тест")
        await db.update_chat(CHAT, approved=1, active=1)
        await db.touch_user(CHAT, 5, "Вася", "vasya")
        await c.post("/v1/events", headers=H, json=event("mute", until=int(time.time()) + 60))
        assert said == []                                  # подколки по умолчанию выключены
        await db.update_chat(CHAT, guard_tease=1)
        await c.post("/v1/events", headers=H, json=event("warn", warns=1, reason="флуд"))
        assert len(said) == 1 and "Вася" in said[0][1] and "флуд" in said[0][1]
        await c.post("/v1/events", headers=H, json=event("ban"))
        assert len(said) == 1                              # не чаще раза в 10 минут
    run(tmp_path, monkeypatch, fn)


@pytest.mark.parametrize("raw,ok", [
    ({"type": "warn", "chat_id": -1, "user_id": 2}, True),
    ({"type": "warn", "chat_id": -1}, False),
    ({"type": "nope", "chat_id": -1, "user_id": 2}, False),
    ({"type": "mute", "chat_id": "x", "user_id": 2}, False),
])
def test_parse_event(raw, ok):
    if ok:
        assert guardlink.parse_event(raw)["type"] == raw["type"]
    else:
        with pytest.raises(ValueError):
            guardlink.parse_event(raw)


def test_plain_nick():
    assert guardlink.plain_nick("𝓑𝓪𝓴𝓼𝓲 👑") == "Baksi"
    assert guardlink.plain_nick("Ｖａｓｙａ_99") == "Vasya_99"
    assert guardlink.plain_nick("  Петя   Пупкин ") == "Петя Пупкин"


def test_card_lines(tmp_path, monkeypatch):
    async def fn(c):
        await db.ensure_chat(CHAT, "Тест")
        assert await guardlink.card_lines(CHAT, 5) == ("🛡 нарушений нет", [])
        await c.post("/v1/events", headers=H, json=event("warn", warns=1, reason="флуд"))
        await c.post("/v1/events", headers=H, json=event("ban", until=0, warns=1, reason="реклама"))
        status, lines = await guardlink.card_lines(CHAT, 5)
        assert status == "🛡 предупреждения 1/3 · бан навсегда"
        assert "бан: реклама" in lines[0] and "предупреждение: флуд" in lines[1]
        await c.post("/v1/events", headers=H, json=event("unban"))
        await c.post("/v1/events", headers=H, json=event("unwarn", warns=0))
        status, lines = await guardlink.card_lines(CHAT, 5)
        assert status == "🛡 сейчас чисто" and len(lines) == 2
    run(tmp_path, monkeypatch, fn)
