"""Кэш каталога в памяти. Пользователи читают только отсюда, база трогается лишь при правках.
После любой правки в админке вызывается `reload()` — полная перезагрузка занимает миллисекунды."""
import hashlib
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
class Category:
    id: int
    label: str
    icon: str | None
    style: str | None
    position: int
    is_active: bool


@dataclass(slots=True)
class AppField:
    id: int
    label: str
    html: str
    kind: str       # text | media | any
    role: str       # name | description | price | contacts | cities | media | ''
    required: bool
    position: int


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
    categories: set[int] = field(default_factory=set)
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
        self.categories: dict[int, Category] = {}
        self.fields: list[AppField] = []
        # (kind, ref, field, lang) -> (перевод, хэш русского текста, с которого переводили)
        self.translations: dict[tuple[str, str, str, str], tuple[str, str]] = {}
        # Готовые отсортированные выборки
        self.main_cities: list[City] = []
        self.other_cities: list[City] = []
        self.by_tag: dict[int, list[Shop]] = {}
        self.by_city: dict[int, list[Shop]] = {}
        self.all_shops: list[Shop] = []
        self.active_categories: list[Category] = []
        self.by_category: dict[int, list[Shop]] = {}
        self.by_city_category: dict[tuple[int, int], list[Shop]] = {}
        self.city_categories: dict[int, list[Category]] = {}
        self._tr_cache: dict[str, "Tr"] = {}

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

        self.categories = {
            r["id"]: Category(r["id"], r["label"], r["icon"], r["style"], r["position"], bool(r["is_active"]))
            for r in await db.fetchall("SELECT * FROM categories ORDER BY position, id")
        }
        self.fields = [
            AppField(r["id"], r["label"], r["html"], r["kind"], r["role"], bool(r["required"]), r["position"])
            for r in await db.fetchall("SELECT * FROM app_fields ORDER BY position, id")
        ]
        self.translations = {
            (r["kind"], r["ref"], r["field"], r["lang"]): (r["value"], r["src_hash"])
            for r in await db.fetchall("SELECT * FROM translations")
        }
        self._tr_cache = {}

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
        for r in await db.fetchall("SELECT shop_id, category_id FROM shop_categories"):
            if r["shop_id"] in shops:
                shops[r["shop_id"]].categories.add(r["category_id"])
        for r in await db.fetchall("SELECT * FROM shop_contacts ORDER BY position, id"):
            if r["shop_id"] in shops:
                shops[r["shop_id"]].contacts.append(Contact(r["id"], r["label"], r["url"], r["icon"], r["style"]))
        for (kind, ref, fld, _), (value, _) in self.translations.items():  # поиск и по переводам
            if kind == "shop" and ref.isdigit() and int(ref) in shops:
                shops[int(ref)].search_key += "\n" + _plain(value).casefold()
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

        self.active_categories = [c for c in self.categories.values() if c.is_active]
        active_cat_ids = {c.id for c in self.active_categories}
        self.by_category = {c.id: [] for c in self.active_categories}
        self.by_city_category = {}
        for shop in self.all_shops:  # all_shops уже отсортирован по рангу
            for cat_id in shop.categories & active_cat_ids:
                self.by_category[cat_id].append(shop)
                for city_id in shop.cities:
                    self.by_city_category.setdefault((city_id, cat_id), []).append(shop)
        self.city_categories = {
            city_id: [c for c in self.active_categories if (city_id, c.id) in self.by_city_category]
            for city_id in self.cities
        }

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

    # ---------- языки ----------
    @property
    def base_lang(self) -> str:
        return self.setting("base_lang", "ru")

    @property
    def languages(self) -> dict[str, str]:
        """Включённые языки: код -> название. Базовый всегда первый."""
        names = self.setting("languages", {"ru": "Русский"})
        enabled = self.setting("enabled_langs", [self.base_lang])
        codes = [self.base_lang] + [c for c in enabled if c != self.base_lang and c in names]
        return {c: names.get(c, c) for c in codes}

    def pick_lang(self, stored: str | None, telegram_code: str | None) -> str:
        langs = self.languages
        if stored in langs:
            return stored
        code = (telegram_code or "").split("-")[0].lower()
        return code if code in langs else self.base_lang

    def tr(self, lang: str) -> "Tr":
        t = self._tr_cache.get(lang)
        if t is None:
            t = self._tr_cache[lang] = Tr(self, lang)
        return t

    def perms_of(self, user_id: int, owners: frozenset[int]) -> set[str] | None:
        """None — не админ. Владельцы из .env имеют все права."""
        if user_id in owners:
            return {"*"}
        return self.admins.get(user_id)


def now() -> int:
    return int(time.time())


def src_hash(value: str) -> str:
    return hashlib.sha1(value.encode()).hexdigest()[:12]


def _plain(html: str) -> str:
    import re
    return re.sub(r"<[^>]+>", "", html)


class Tr:
    """Тексты каталога на языке пользователя. Нет перевода — показывается базовый (русский) текст."""
    __slots__ = ("cat", "lang", "is_base")

    def __init__(self, cat: Catalog, lang: str) -> None:
        self.cat = cat
        self.lang = lang
        self.is_base = lang == cat.base_lang

    def get(self, kind: str, ref: object, fld: str, base: str) -> str:
        if self.is_base or not base:
            return base
        found = self.cat.translations.get((kind, str(ref), fld, self.lang))
        return found[0] if found else base

    def text(self, key: str) -> str:
        return self.get("text", key, "html", self.cat.text(key).html)

    def button(self, key: str) -> Button:
        b = self.cat.button(key)
        return Button(b.key, self.get("btn", key, "label", b.label), b.icon, b.style)

    def label(self, kind: str, obj: Any) -> str:
        return self.get(kind, obj.id, "label", obj.label)

    def html(self, kind: str, obj: Any) -> str:
        return self.get(kind, obj.id, "html", obj.html)
