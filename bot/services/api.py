"""Внутренний API Бакси для модератора (раздел 6 GUARD_SPEC). Слушает только 127.0.0.1, снаружи его нет.
Каждый запрос с заголовком X-Key: <BAXI_API_KEY>, без ключа 401. Всё в JSON, время в unix-секундах.

GET  /v1/chat/{chat_id}           {"known", "title", "active", "paid", "trial", "free", "until"}
GET  /v1/chat/{chat_id}/trusted   {"admins": [id, ...], "vip": [id, ...]}  их модератор не трогает автоматикой
POST /v1/events                   событие модератора, ответ {"ok": true}
GET  /v1/user/{user_id}           ник человека: красивый, простой, эмодзи (для модератора и сайта)
GET  /v1/users?ids=1,2,3          то же пачкой: {"users": {"1": {...}, ...}}
GET  /v1/ping                     {"ok": true}

Без BAXI_API_KEY в .env сервер не поднимается (так и у копий клиентов)."""

import functools
import hmac
import json
import logging
import time

from aiohttp import web

from bot import config, db
from bot.services import guardlink

log = logging.getLogger(__name__)

HOST = "127.0.0.1"
ADMINS_TTL = 300
MAX_BATCH = 200
_admins: dict[int, tuple[float, list[int]]] = {}
BOT = web.AppKey("bot", object)
state = {"listening": ""}


def _json(data: dict, status: int = 200) -> web.Response:
    return web.json_response(data, status=status, dumps=functools.partial(json.dumps, ensure_ascii=False))


@web.middleware
async def auth(request: web.Request, handler):
    key = request.headers.get("X-Key", "")
    if not config.BAXI_API_KEY or not hmac.compare_digest(key.encode(), config.BAXI_API_KEY.encode()):
        return _json({"ok": False, "error": "unauthorized"}, 401)
    try:
        return await handler(request)
    except web.HTTPException:
        raise
    except (ValueError, TypeError, KeyError):
        return _json({"ok": False, "error": "bad request"}, 400)
    except Exception:
        log.exception("Ошибка API на %s", request.path)
        return _json({"ok": False, "error": "internal"}, 500)


async def ping(_request: web.Request) -> web.Response:
    return _json({"ok": True})


def chat_payload(chat) -> dict:
    """Ответ про чат. paid: аренда оплачена или чат без срока (твои чаты); trial: идёт пробный."""
    if chat is None:
        return {"known": False, "title": "", "active": False, "paid": False, "trial": False, "free": False,
                "until": 0}
    from bot.services import license
    until = int(chat["rent_until"] or 0)
    free = bool(chat["free"])
    expired = bool(until) and until < time.time()
    active = bool(chat["active"] and chat["approved"]) and not license.sleeping()
    trial = bool(chat["trial"]) and not free and not expired
    paid = active and not free and not trial and not expired
    return {"known": True, "title": chat["title"] or "", "active": active, "paid": paid, "trial": trial and active,
            "free": free, "until": until}


async def chat_info(request: web.Request) -> web.Response:
    chat_id = int(request.match_info["chat_id"])
    return _json(chat_payload(await db.get_chat(chat_id)))


async def admins_of(bot, chat_id: int) -> list[int]:
    hit = _admins.get(chat_id)
    if hit and time.monotonic() - hit[0] < ADMINS_TTL:
        return hit[1]
    try:
        ids = [m.user.id for m in await bot.get_chat_administrators(chat_id)]
    except Exception:
        return hit[1] if hit else []
    _admins[chat_id] = (time.monotonic(), ids)
    return ids


async def vip_in_chat(chat_id: int) -> list[int]:
    async with db.conn().execute(
            "SELECT p.user_id FROM perks p JOIN users u ON u.user_id = p.user_id AND u.chat_id = ? "
            "WHERE p.vip_until > ?", (chat_id, time.time())) as cur:
        return [r[0] for r in await cur.fetchall()]


async def trusted(request: web.Request) -> web.Response:
    chat_id = int(request.match_info["chat_id"])
    if await db.get_chat(chat_id) is None:
        return _json({"admins": [], "vip": []})
    return _json({"admins": await admins_of(request.app[BOT], chat_id), "vip": await vip_in_chat(chat_id)})


async def events(request: web.Request) -> web.Response:
    try:
        data = await request.json()
    except json.JSONDecodeError:
        return _json({"ok": False, "error": "bad json"}, 400)
    ev = guardlink.parse_event(data)
    await guardlink.handle(request.app[BOT], ev)
    return _json({"ok": True})


async def user(request: web.Request) -> web.Response:
    return _json(await guardlink.nick_info(int(request.match_info["user_id"])))


async def users(request: web.Request) -> web.Response:
    raw = request.query.get("ids", "")
    ids = [int(x) for x in raw.split(",") if x.strip()][:MAX_BATCH]
    return _json({"users": {str(i): await guardlink.nick_info(i) for i in ids}})


def make_app(bot) -> web.Application:
    app = web.Application(middlewares=[auth], client_max_size=64 * 1024)
    app[BOT] = bot
    app.router.add_get("/v1/ping", ping)
    app.router.add_get(r"/v1/chat/{chat_id:-?\d+}", chat_info)
    app.router.add_get(r"/v1/chat/{chat_id:-?\d+}/trusted", trusted)
    app.router.add_post("/v1/events", events)
    app.router.add_get(r"/v1/user/{user_id:\d+}", user)
    app.router.add_get("/v1/users", users)
    return app


async def start(bot) -> web.AppRunner | None:
    if not config.BAXI_API_KEY:
        log.info("BAXI_API_KEY пуст: API Бакси для модератора не запущен")
        return None
    runner = web.AppRunner(make_app(bot), access_log=None)
    await runner.setup()
    try:
        await web.TCPSite(runner, HOST, config.BAXI_API_PORT).start()
    except OSError as exc:
        log.error("API Бакси не запустился на %s:%s: %s", HOST, config.BAXI_API_PORT, exc)
        await runner.cleanup()
        return None
    state["listening"] = f"{HOST}:{config.BAXI_API_PORT}"
    log.info("API Бакси слушает %s", state["listening"])
    return runner
