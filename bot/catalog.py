"""Кэш каталога в памяти. Пользователи читают только отсюда, база трогается лишь при правках.
После любой правки в админке вызывается `reload()` — полная перезагрузка занимает миллисекунды."""
import json
import time
from dataclasses import dataclass, field
from typing import Any

from .db import Database

STYLES = (None, "primary", "success", "danger")
STYLE_NAMES = {None: "обычная", "primary": "синяя", "success": "зелёная", "danger": "красная"}


@dataclass(slots=True)
class Button:
    key: str
    label: str
    icon: str | None
    style: str | None


@dataclass(slots=True)
class Text:
    key: str
    html: str
    media_id: int | None


@dataclass(slots=True)
class MenuItem:
    id: int
    parent_id: int | None
    kind: str
    payload: str | None
    label: str
    icon: str | None
    style: str | None
    html: str
    media_id: int | None
    row: int
    position: int
    is_system: bool
    is_active: bool
    children: list["MenuItem"] = field(default_factory=list)


@dataclass(slots=True)
class Tag:
    id: int
    label: str
    position: int


@dataclass(slots=True)
class City:
    id: int
    label: str
    icon: str | None
    style: str | None
    is_main: bool
    position: int
    is_active: bool


@dataclass(slots=True)
class Contact:
    id: int
    label: str
    url: str
    icon: str | None
    style: str | None


@dataclass(slots=True)
class Shop:
    id: int
    label: str
    icon: str | None
    style: str | None
    html: str
    plain: str
    media_id: int | None
    verified: bool
    position: int
    is_active: bool
    tags: dict[int, int | None] = field(default_factory=dict)  # tag_id -> expires_at
    cities: set[int] = field(default_factory=set)
    contacts: list[Contact] = field(default_factory=list)
    search_key: str = ""


class Catalog:
    def __init__(self, db: Database) -> None:
        self.db = db
        self.settings: dict[str, Any] = {}
        self.texts: dict[str, Text] = {}
        self.buttons: dict[str, Button] = {}
        self.menu: dict[int, MenuItem] = {}
        self.root_id: int = 0
        self.tags: dict[int, Tag] = {}
        self.cities: dict[int, City] = {}
        self.shops: dict[int, Shop] = {}
        self.admins: dict[int, set[str]] = {}
        # Готовые отсортированные выборки
        self.main_cities: list[City] = []
        self.other_cities: list[City] = []
        self.by_tag: dict[int, list[Shop]] = {}
        self.by_city: dict[int, list[Shop]] = {}
        self.all_shops: list[Shop] = []

    # ---------- загрузка ----------
    async def reload(self) -> None:
        db = self.db
        self.settings = {r["key"]: json.loads(r["value"]) for r in await db.fetchall("SELECT key, value FROM settings")}
        self.texts = {r["key"]: Text(r["key"], r["html"], r["media_id"]) for r in await db.fetchall("SELECT * FROM texts")}
        self.buttons = {
            r["key"]: Button(r["key"], r["label"], r["icon"], r["style"])
            for r in await db.fetchall("SELECT * FROM buttons")
        }

        menu: dict[int, MenuItem] = {}
        for r in await db.fetchall("SELECT * FROM menu_items ORDER BY row, position, id"):
            menu[r["id"]] = MenuItem(
                r["id"], r["parent_id"], r["kind"], r["payload"], r["label"], r["icon"], r["style"],
                r["html"], r["media_id"], r["row"], r["position"], bool(r["is_system"]), bool(r["is_active"]),
            )
        for item in menu.values():
            if item.parent_id in menu:
                menu[item.parent_id].children.append(item)
        roots = [i for i in menu.values() if i.parent_id is None]
        self.root_id = next((i.id for i in roots if i.is_system), roots[0].id if roots else 0)
        self.menu = menu

        self.tags = {r["id"]: Tag(r["id"], r["label"], r["position"]) for r in await db.fetchall("SELECT * FROM tags ORDER BY position, id")}
        self.cities = {
            r["id"]: City(r["id"], r["label"], r["icon"], r["style"], bool(r["is_main"]), r["position"], bool(r["is_active"]))
            for r in await db.fetchall("SELECT * FROM cities ORDER BY position, id")
        }

        shops: dict[int, Shop] = {}
        for r in await db.fetchall("SELECT * FROM shops ORDER BY position, id"):
            shops[r["id"]] = Shop(
                r["id"], r["label"], r["icon"], r["style"], r["html"], r["plain"], r["media_id"],
                bool(r["verified"]), r["position"], bool(r["is_active"]),
                search_key=f"{r['label']}\n{r['plain']}".casefold(),
            )
        for r in await db.fetchall("SELECT shop_id, tag_id, expires_at FROM shop_tags"):
            if r["shop_id"] in shops and r["tag_id"] in self.tags:
                shops[r["shop_id"]].tags[r["tag_id"]] = r["expires_at"]
        for r in await db.fetchall("SELECT shop_id, city_id FROM shop_cities"):
            if r["shop_id"] in shops:
                shops[r["shop_id"]].cities.add(r["city_id"])
        for r in await db.fetchall("SELECT * FROM shop_contacts ORDER BY position, id"):
            if r["shop_id"] in shops:
                shops[r["shop_id"]].contacts.append(Contact(r["id"], r["label"], r["url"], r["icon"], r["style"]))
        self.shops = shops

        self.admins = {r["user_id"]: set(filter(None, r["perms"].split(","))) for r in await db.fetchall("SELECT * FROM admins")}
        self._build_indexes()

    def _build_indexes(self) -> None:
        active_cities = [c for c in self.cities.values() if c.is_active]
        self.main_cities = [c for c in active_cities if c.is_main]
        self.other_cities = sorted((c for c in active_cities if not c.is_main), key=lambda c: (c.position, c.label))

        active = [s for s in self.shops.values() if s.is_active]
        self.all_shops = sorted(active, key=self.shop_rank)
        self.by_tag = {tag_id: [] for tag_id in self.tags}
        self.by_city = {city_id: [] for city_id in self.cities}
        for shop in active:
            for tag_id in shop.tags:
                self.by_tag[tag_id].append(shop)
            for city_id in shop.cities:
                if city_id in self.by_city:
                    self.by_city[city_id].append(shop)
        for lst in self.by_tag.values():
            lst.sort(key=lambda s: (s.position, s.id))
        for lst in self.by_city.values():
            lst.sort(key=self.shop_rank)

    def shop_rank(self, shop: Shop) -> tuple[int, int, int]:
        """Сначала магазины с меткой повыше (Премиум, потом Топ), потом остальные."""
        tag_pos = min((self.tags[t].position for t in shop.tags if t in self.tags), default=1_000_000)
        return (tag_pos, shop.position, shop.id)

    # ---------- доступ ----------
    def setting(self, key: str, default: Any = 0) -> Any:
        return self.settings.get(key, default)

    def text(self, key: str) -> Text:
        return self.texts.get(key) or Text(key, key, None)

    def button(self, key: str) -> Button:
        return self.buttons.get(key) or Button(key, key, None, None)

    def active_children(self, item_id: int) -> list[MenuItem]:
        item = self.menu.get(item_id)
        return [c for c in item.children if c.is_active] if item else []

    def search(self, query: str, limit: int = 100) -> list[Shop]:
        words = query.casefold().split()
        if not words:
            return []
        return [s for s in self.all_shops if all(w in s.search_key for w in words)][:limit]

    def perms_of(self, user_id: int, owners: frozenset[int]) -> set[str] | None:
        """None — не админ. Владельцы из .env имеют все права."""
        if user_id in owners:
            return {"*"}
        return self.admins.get(user_id)


def now() -> int:
    return int(time.time())
