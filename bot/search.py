"""Умный поиск: «vpn алматы до 5000», «подарки в астане», «gift shop».

Из запроса выделяются фильтры — город, категория, метка, цена, — а оставшиеся слова ищутся
в названии, описании и переводах магазина. Слова сравниваются по основе,
поэтому «подарков», «подарки» и «подарок» находят одно и то же."""
import re
from dataclasses import dataclass, field

from .catalog import Catalog, Shop

CURRENCY = r"(?:₸|тг|тенге|kzt|₽|руб(?:лей|\.)?|р\.|\$|usd|сом)"
_NUM = r"\d[\d\s]{0,9}(?:[.,]\d+)?\s*(?:к|k|тыс\.?)?"
# цены в тексте карточки: «1500 тг», «от 2 000₸», «цена 900»
PRICE_IN_TEXT = re.compile(rf"(?:(?:от|до|цена|прайс|стоимость)\s*({_NUM})|({_NUM})\s*{CURRENCY})", re.I)
MAX_RE = re.compile(rf"(?:до|дешевле|не дороже|max|макс(?:имум)?|<=?|≤)\s*({_NUM})\s*{CURRENCY}?", re.I)
MIN_RE = re.compile(rf"(?:от|дороже|min|мин(?:имум)?|>=?|≥)\s*({_NUM})\s*{CURRENCY}?", re.I)
BARE_RE = re.compile(rf"(?<![\w])({_NUM})\s*{CURRENCY}?(?![\w])", re.I)
WORD_RE = re.compile(r"[\w@]+", re.U)
STOP_WORDS = {"в", "во", "на", "и", "или", "по", "для", "с", "со", "из", "у", "the", "in", "a", "an", "and", "for",
              "магазин", "магазины", "купить", "нужен", "нужно", "хочу", "где", "есть"}


def to_number(raw: str) -> int | None:
    raw = raw.strip().lower().replace(" ", "").replace(",", ".")
    mult = 1000 if raw.endswith(("к", "k", "тыс", "тыс.")) else 1
    raw = re.sub(r"[^\d.]", "", raw)
    try:
        return int(float(raw) * mult) if raw else None
    except ValueError:
        return None


def shop_prices(text: str) -> list[int]:
    out = []
    for m in PRICE_IN_TEXT.finditer(text):
        n = to_number(m.group(1) or m.group(2))
        if n and n >= 10:
            out.append(n)
    return out


_price_cache: dict[int, tuple[str, list[int]]] = {}


def _prices(shop: Shop) -> list[int]:
    cached = _price_cache.get(shop.id)
    if cached is None or cached[0] != shop.plain:
        cached = _price_cache[shop.id] = (shop.plain, shop_prices(shop.plain))
    return cached[1]


def stem(word: str) -> str:
    """Грубая основа слова: отрезаем окончание, чтобы «подарков» ≈ «подарки»."""
    word = word.casefold().replace("ё", "е")
    if len(word) > 6:
        return word[:-2]
    if len(word) > 4:
        return word[:-1]
    return word


_VOWELS = re.compile(r"(?<=.)[аеиоуыэюяaeiouy]")


def skeleton(word: str) -> str:
    """Слово без гласных (кроме первой буквы): «хаш», «хеш», «хэш» → «хш», «hash» → «hsh», «sort» → «srt».
    Так одно написание кода или названия покрывает все похожие. Латиница и кириллица не смешиваются."""
    return _VOWELS.sub("", word.casefold().replace("ё", "е"))


def _same_code(token: str, name: str) -> bool:
    """Совпадение по согласным, только для слов от 3 букв: «ds» и «дус» так не склеятся."""
    return len(token) >= 3 and len(name) >= 3 and " " not in name and skeleton(token) == skeleton(name)


def _names(label: str) -> str:
    """Название без эмодзи: «🔐 VPN» → «vpn»."""
    return " ".join(WORD_RE.findall(label)).casefold().replace("ё", "е")


def _matches_name(token: str, name: str) -> bool:
    """Слово запроса совпадает с названием города/категории с учётом падежей («астане» → «астана»)."""
    if not name:
        return False
    if token == name:
        return True
    if len(name) < 4:  # «топ» ↔ «топы», «vpn» ↔ «vpn»
        return token.startswith(name) and len(token) <= len(name) + 2
    if len(token) >= 4 and len(name) >= 4:
        base = name[:max(4, len(name) - 2)]
        return token.startswith(base) or name.startswith(stem(token))
    return False


@dataclass
class Query:
    words: list[str] = field(default_factory=list)
    cities: set[int] = field(default_factory=set)
    categories: set[int] = field(default_factory=set)
    category_stems: list[str] = field(default_factory=list)  # магазин без галочки, но с «vpn» в тексте тоже найдётся
    tags: set[int] = field(default_factory=set)
    price_max: int | None = None
    price_min: int | None = None

    @property
    def has_filters(self) -> bool:
        return bool(self.cities or self.categories or self.tags or self.price_max or self.price_min)


def synonyms(cat: Catalog, word: str) -> list[str]:
    """Похожие слова из общего словаря: «впн» → [«впн», «vpn», «вэпээн»]."""
    word = word.casefold().replace("ё", "е")
    w_stem = stem(word)
    for group in cat.setting("search_synonyms", []):
        words = [g.casefold().replace("ё", "е").strip() for g in group if g.strip()]
        if any(word == g or w_stem == stem(g) for g in words):
            return list(dict.fromkeys([word, *words]))
    return [word]


def parse(cat: Catalog, text: str) -> Query:
    q = Query()
    text = " " + text.casefold().replace("ё", "е") + " "

    m = MAX_RE.search(text)
    if m:
        q.price_max = to_number(m.group(1))
        text = text.replace(m.group(0), " ")
    m = MIN_RE.search(text)
    if m:
        q.price_min = to_number(m.group(1))
        text = text.replace(m.group(0), " ")
    if q.price_max is None and q.price_min is None:
        m = BARE_RE.search(text)  # просто число — это бюджет: «vpn 3000»
        n = to_number(m.group(1)) if m else None
        if n and n >= 100:
            q.price_max = n
            text = text.replace(m.group(0), " ")

    # названия на всех языках: город «Алматы» найдётся и как «Almaty»
    def names(kind: str, items) -> list[tuple[int, str]]:
        out = []
        for obj in items:
            out.append((obj.id, _names(obj.label)))
            for lang in cat.languages:
                tr = cat.translations.get((kind, str(obj.id), "label", lang))
                if tr:
                    out.append((obj.id, _names(tr[0])))
        return out

    cities = names("city", [c for c in cat.cities.values() if c.is_active])
    # категория узнаётся по названию и по «как ещё пишут», регистр и гласные не важны
    categories = [(c.id, name) for c in cat.active_categories
                  for name in (_names(w) for w in [c.label, *c.words.split(",")]) if name]
    tags = names("tag", cat.tags.values())

    tokens = WORD_RE.findall(text)
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        pair = f"{tok} {tokens[i + 1]}" if i + 1 < len(tokens) else ""
        hit = False
        variants = synonyms(cat, tok)  # «впн» узнаётся как категория VPN, если так записано в словаре
        for pool, target in ((cities, q.cities), (categories, q.categories), (tags, q.tags)):
            for obj_id, name in pool:
                if pair and " " in name and _matches_name(pair, name):  # «усть каменогорск»
                    target.add(obj_id)
                    i += 1
                    hit = True
                    break
                if target is q.categories:  # одно слово может подходить к нескольким категориям: берём все
                    if any(_matches_name(v, name) or _same_code(v, name) for v in variants):
                        target.add(obj_id)
                        hit = True
                    continue
                if any(_matches_name(v, name) for v in variants):
                    target.add(obj_id)
                    hit = True
                    break
            if hit:
                if target is q.categories:
                    q.category_stems.extend(variants)
                break
        if not hit and tok not in STOP_WORDS and not tok.isdigit():
            q.words.append(tok)
        i += 1
    return q


def _mentions(key: str, words: list[str]) -> bool:
    """Есть ли слово в тексте магазина. Короткие коды (ST, DS) только целым словом, иначе «ст» найдётся в «стоимость»."""
    tokens = None
    for w in words:
        if len(w) <= 3:
            tokens = tokens if tokens is not None else set(WORD_RE.findall(key))
            if w in tokens:
                return True
        elif stem(w) in key:
            return True
    return False


def run(cat: Catalog, text: str, limit: int = 100) -> tuple[list[Shop], Query]:
    q = parse(cat, text)
    if not q.words and not q.has_filters:
        return [], q
    # каждое слово запроса — группа вариантов: само слово и его синонимы из словаря
    groups = [synonyms(cat, w) for w in q.words]
    stems = [[stem(v) for v in group] for group in groups]
    scored: list[tuple[int, Shop]] = []
    for shop in cat.all_shops:
        if q.cities and not (shop.cities & q.cities):
            continue
        key = shop.search_key.replace("ё", "е")
        if q.categories and not (shop.categories & q.categories) and not _mentions(key, q.category_stems):
            continue
        if q.tags and not (set(shop.tags) & q.tags):
            continue
        if q.price_max is not None or q.price_min is not None:
            prices = _prices(shop)
            if not prices:
                continue
            if q.price_max is not None and min(prices) > q.price_max:
                continue
            if q.price_min is not None and max(prices) < q.price_min:
                continue
        if not all(_mentions(key, group) for group in groups):
            continue
        name = _names(shop.label)
        score = sum(2 for group in stems if any(s in name for s in group))  # совпадение в названии — выше
        scored.append((score, shop))
    scored.sort(key=lambda x: (-x[0], cat.shop_rank(x[1])))
    return [s for _, s in scored[:limit]], q


def describe(cat: Catalog, tr, q: Query) -> str:
    """Строка с распознанными фильтрами: «🏙 Алматы · 🗂 VPN · 💰 до 5000»."""
    parts = [f"🏙 {tr.label('city', cat.cities[c])}" for c in q.cities if c in cat.cities]
    parts += [tr.label("cat", cat.categories[c]) for c in q.categories if c in cat.categories]
    parts += [f"🏷 {tr.label('tag', cat.tags[t])}" for t in q.tags if t in cat.tags]
    if q.price_min is not None and q.price_max is not None:
        parts.append(f"💰 {q.price_min}–{q.price_max}")
    elif q.price_max is not None:
        parts.append(f"💰 ≤ {q.price_max}")
    elif q.price_min is not None:
        parts.append(f"💰 ≥ {q.price_min}")
    return " · ".join(parts)

