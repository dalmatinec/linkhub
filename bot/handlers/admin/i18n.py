"""Админка: языки и переводы. Без внешних API — перевод вписывает человек:
по одному тексту прямо в админке или файлом (выгрузил → перевёл где угодно → загрузил)."""
import json
import re
from dataclasses import dataclass
from html import escape

from aiogram.types import BufferedInputFile, Message

from ...app import App
from ...catalog import src_hash
from ...richtext import html_error, message_html, parse_label
from .content import BUTTON_NAMES, TEXT_NAMES
from .core import TARGETS, Ctx, InputError, Rows, ViewResult, action, allowed, b, back_btn, on_input, snippet, view

P = "texts"
FIELD_TITLES = {"label": "Текст кнопки / название", "html": "Текст экрана"}
MAX_FILE = 2 * 1024 * 1024


@dataclass(slots=True)
class Item:
    kind: str
    ref: str
    field: str
    title: str
    base: str


def translatables(app: App) -> list[Item]:
    """Всё, что можно перевести, — с человеческим названием."""
    cat = app.catalog
    out: list[Item] = []
    for key, t in cat.texts.items():
        if key in TEXT_NAMES and t.html:
            out.append(Item("text", key, "html", TEXT_NAMES[key], t.html))
    for key, btn in cat.buttons.items():
        if key in BUTTON_NAMES:
            out.append(Item("btn", key, "label", f"Кнопка: {BUTTON_NAMES[key]}", btn.label))
    for item in cat.menu.values():
        is_root = item.id == cat.root_id
        name = "Приветствие" if is_root else f"Меню: {item.label}"
        if not is_root:
            out.append(Item("item", str(item.id), "label", f"{name}: кнопка", item.label))
        if item.html:
            out.append(Item("item", str(item.id), "html", f"{name}: текст экрана", item.html))
    out += [Item("city", str(c.id), "label", f"Город: {c.label}", c.label) for c in cat.cities.values()]
    out += [Item("tag", str(t.id), "label", f"Метка: {t.label}", t.label) for t in cat.tags.values()]
    out += [Item("cat", str(c.id), "label", f"Категория: {c.label}", c.label) for c in cat.categories.values()]
    for f in cat.fields:
        out.append(Item("field", str(f.id), "label", f"Анкета, {f.label}: название", f.label))
        out.append(Item("field", str(f.id), "html", f"Анкета, {f.label}: вопрос", f.html))
    for s in cat.shops.values():
        out.append(Item("shop", str(s.id), "label", f"Магазин {s.label}: кнопка", s.label))
        if s.html:
            out.append(Item("shop", str(s.id), "html", f"Магазин {s.label}: карточка", s.html))
    return out


def status(app: App, it: Item, lang: str) -> str:
    """'ok' — переведено, 'old' — русский текст поменялся после перевода, 'none' — перевода нет."""
    found = app.catalog.translations.get((it.kind, it.ref, it.field, lang))
    if found is None:
        return "none"
    return "ok" if found[1] == src_hash(it.base) else "old"


def other_langs(app: App) -> dict[str, str]:
    cat = app.catalog
    return {c: n for c, n in cat.languages.items() if c != cat.base_lang}


# ---------- обзор ----------
@view("langs", P)
async def view_languages(ctx: Ctx) -> ViewResult:
    app = ctx.app
    cat = app.catalog
    names = cat.setting("languages", {})
    enabled = cat.languages
    items = translatables(app)
    lines = ["🌐 <b>Языки и переводы</b>\n",
             f"Основной язык: {names.get(cat.base_lang, cat.base_lang)}. На нём всё, что вы пишете в админке.",
             "Пользователь видит перевод, а если его нет, то основной текст. Автоперевода нет: "
             "вы вписываете перевод сами (или отдаёте файл переводчику).\n"]
    rows: Rows = []
    for code, name in names.items():
        if code == cat.base_lang:
            continue
        on = code in enabled
        st = [status(app, it, code) for it in items]
        lines.append(f"{name}: {'включён' if on else 'выключен'} · переведено {st.count('ok')} из {len(items)}"
                     + (f" · ⚠️ устарело {st.count('old')}" if st.count("old") else ""))
        rows.append([b(f"{'✅' if on else '▫️'} {name}", f"x:langtog:{code}")])
    lines.append("\n⚠️ Устарело значит, что вы поменяли русский текст после перевода. Перевод всё ещё показывается, "
                 "но его стоит обновить.")
    rows.append([b("📤 Файл: только новое и устаревшее", "x:trexp:todo")])
    rows.append([b("📤 Файл: все тексты", "x:trexp:all")])
    rows.append([b("📥 Загрузить переведённый файл", "x:trimp", "success")])
    rows.append(back_btn("a:cfg"))
    return "\n".join(lines), rows


@action("langtog", P)
async def act_language_toggle(ctx: Ctx, code: str):
    cat = ctx.app.catalog
    enabled = list(cat.setting("enabled_langs", [cat.base_lang]))
    if code in enabled:
        enabled.remove(code)
    elif code in cat.setting("languages", {}):
        enabled.append(code)
    await ctx.app.db.execute("INSERT OR REPLACE INTO settings(key, value) VALUES ('enabled_langs', ?)",
                             (json.dumps(enabled),))
    await ctx.reload()
    await ctx.log("lang.toggle", code)
    return "a:langs"


# ---------- перевод одного объекта ----------
def _check(ctx: Ctx, kind: str) -> None:
    """Переводить объект может тот, кто вправе его редактировать (или отвечает за тексты)."""
    if not (allowed(ctx.app, ctx.user_id, P) or (kind in TARGETS and allowed(ctx.app, ctx.user_id, TARGETS[kind][3]))):
        raise InputError("Нет доступа.")


@view("trl")
async def view_translation(ctx: Ctx, kind: str, key: str) -> ViewResult:
    _check(ctx, kind)
    app = ctx.app
    items = [it for it in translatables(app) if it.kind == kind and it.ref == key]
    langs = other_langs(app)
    back = TARGETS[kind][2].format(key) if kind in TARGETS else "a:langs"
    if not langs:
        return ("🌐 Других языков не включено. Включите их в разделе 🌐 Языки.",
                [[b("🌐 Языки", "a:langs")], back_btn(back)])
    icons = {"ok": "✅", "old": "⚠️", "none": "▫️"}
    lines = ["🌐 <b>Перевод</b>\n"]
    rows: Rows = []
    for it in items:
        lines.append(f"<b>{escape(it.title)}</b>\n🇷🇺 {snippet(it.base, 200)}")
        for code, name in langs.items():
            st = status(app, it, code)
            value = app.catalog.translations.get((kind, key, it.field, code))
            lines.append(f"{icons[st]} {escape(name)}: {snippet(value[0], 200) if value else '<i>нет перевода</i>'}")
            r = [b(f"✏️ {name} · {FIELD_TITLES[it.field].split(' /')[0]}", f"x:tred:{kind}:{key}:{it.field}:{code}")]
            if value:
                r.append(b("✖️", f"x:trdel:{kind}:{key}:{it.field}:{code}"))
            rows.append(r)
        lines.append("")
    lines.append("✅ переведено, ⚠️ русский текст поменялся после перевода, ▫️ перевода нет "
                 "(показывается русский).")
    rows.append(back_btn(back))
    return "\n".join(lines), rows


@action("tred")
async def act_translation_edit(ctx: Ctx, kind: str, key: str, fld: str, lang: str):
    _check(ctx, kind)
    name = ctx.app.catalog.setting("languages", {}).get(lang, lang)
    hint = ("Отправьте перевод текста кнопки." if fld == "label"
            else "Отправьте перевод текста. Форматирование и премиум-эмодзи сохранятся.")
    return await ctx.ask("tred", f"🌐 {escape(name)}\n{hint}", f"a:trl:{kind}:{key}", kind, key, fld, lang)


async def save_translation(app: App, kind: str, key: str, fld: str, lang: str, value: str) -> None:
    base = next((it.base for it in translatables(app) if (it.kind, it.ref, it.field) == (kind, key, fld)), None)
    if base is None:
        raise InputError("Этот текст больше не существует.")
    await app.db.execute(
        "INSERT OR REPLACE INTO translations(kind, ref, field, lang, value, src_hash) VALUES (?, ?, ?, ?, ?, ?)",
        (kind, key, fld, lang, value, src_hash(base)))


@on_input("tred")
async def in_translation_edit(ctx: Ctx, message: Message, kind: str, key: str, fld: str, lang: str):
    _check(ctx, kind)
    if not message.text:
        raise InputError("Нужен текст.")
    if fld == "label":
        value, _ = parse_label(message)
    else:
        value, _ = message_html(message)
    if not value:
        raise InputError("Пустой перевод.")
    await save_translation(ctx.app, kind, key, fld, lang, value)
    await ctx.reload()
    await ctx.log("tr.edit", f"{kind}/{key}/{fld}/{lang}")
    ctx.notice = "✅ Перевод сохранён"
    return f"a:trl:{kind}:{key}"


@action("trdel")
async def act_translation_delete(ctx: Ctx, kind: str, key: str, fld: str, lang: str):
    _check(ctx, kind)
    await ctx.app.db.execute("DELETE FROM translations WHERE kind = ? AND ref = ? AND field = ? AND lang = ?",
                             (kind, key, fld, lang))
    await ctx.reload()
    return f"a:trl:{kind}:{key}"


# ---------- файл для переводчика ----------
FILE_HEAD = """# Перевод текстов бота.
# Впишите перевод после kk: и en: (можно в несколько строк). Строку ru: не меняйте, она для сверки.
# Теги <b>…</b>, <i>…</i>, <a href="…">…</a>, <tg-emoji …>…</tg-emoji> оставляйте как есть:
# это жирный шрифт, ссылки и премиум-эмодзи. Слова в фигурных скобках {город}, {имя} не переводите.
# Пустую строку перевода бот пропустит.
"""


def build_export(app: App, only_todo: bool) -> tuple[str, int]:
    langs = other_langs(app)
    base = app.catalog.base_lang
    blocks = [FILE_HEAD]
    count = 0
    for it in translatables(app):
        states = {code: status(app, it, code) for code in langs}
        if only_todo and all(s == "ok" for s in states.values()):
            continue
        count += 1
        lines = [f"=== {it.kind}/{it.ref}/{it.field} | {it.title} ===", f"{base}: {it.base}"]
        for code in langs:
            found = app.catalog.translations.get((it.kind, it.ref, it.field, code))
            mark = "  # ⚠️ русский текст изменился, проверьте" if states[code] == "old" else ""
            lines.append(f"{code}: {found[0] if found else ''}{mark}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks) + "\n", count


@action("trexp", P)
async def act_translation_export(ctx: Ctx, mode: str):
    app = ctx.app
    if not other_langs(app):
        ctx.notice = "Сначала включите хотя бы один язык."
        return "a:langs"
    text, count = build_export(app, only_todo=mode == "todo")
    if count == 0:
        ctx.notice = "✅ Всё переведено, выгружать нечего."
        return "a:langs"
    await app.bot.send_document(
        ctx.chat_id, BufferedInputFile(text.encode("utf-8"), filename=f"translations_{mode}.txt"),
        caption=f"🌐 Текстов в файле: {count}. Переведите и загрузите обратно кнопкой 📥 Загрузить.")
    await ctx.toast("Файл отправлен ниже")
    return None


HEADER_RE = re.compile(r"^=== (\w+)/([^/]+)/(label|html)(?: \|.*)? ===\s*$")


def parse_import(text: str, codes: list[str]) -> dict[tuple[str, str, str, str], str]:
    """Разбирает файл перевода → {(kind, ref, field, lang): value}."""
    lang_re = re.compile(rf"^({'|'.join(map(re.escape, codes))}):\s?(.*)$")
    result: dict[tuple[str, str, str, str], str] = {}
    current: tuple[str, str, str] | None = None
    lang: str | None = None
    buf: list[str] = []

    def flush() -> None:
        if current and lang:
            value = re.sub(r"\s*# ⚠️ русский текст изменился.*$", "", "\n".join(buf)).strip()
            if value:
                result[(*current, lang)] = value

    for line in text.splitlines():
        if line.startswith("#") and current is None:
            continue
        m = HEADER_RE.match(line)
        if m:
            flush()
            current, lang, buf = (m.group(1), m.group(2), m.group(3)), None, []
            continue
        m = lang_re.match(line)
        if m and current:
            flush()
            lang, buf = m.group(1), [m.group(2)]
            continue
        if lang is not None:
            buf.append(line)
    flush()
    return result


@action("trimp", P)
async def act_translation_import(ctx: Ctx):
    return await ctx.ask("trimp", "Пришлите файл перевода (.txt), который выгрузили из бота.", "a:langs")


@on_input("trimp", P)
async def in_translation_import(ctx: Ctx, message: Message):
    app = ctx.app
    doc = message.document
    if doc is None or (doc.file_size or 0) > MAX_FILE:
        raise InputError("Нужен .txt файл, выгруженный из бота (до 2 МБ).")
    buf = await app.bot.download(doc.file_id)
    try:
        text = buf.getvalue().decode("utf-8-sig")
    except UnicodeDecodeError:
        raise InputError("Файл должен быть в кодировке UTF-8.")
    langs = other_langs(app)
    parsed = parse_import(text, [app.catalog.base_lang, *langs])
    known = {(it.kind, it.ref, it.field): it for it in translatables(app)}
    saved, errors = 0, []
    for (kind, ref, fld, lang), value in parsed.items():
        if lang not in langs:
            continue  # строка основного языка — только для сверки
        it = known.get((kind, ref, fld))
        if it is None:
            errors.append(f"{kind}/{ref}: текст не найден (удалён?)")
            continue
        err = html_error(value) if fld == "html" else None
        if err:
            errors.append(f"{it.title} [{lang}]: {err}")
            continue
        await app.db.execute(
            "INSERT OR REPLACE INTO translations(kind, ref, field, lang, value, src_hash) VALUES (?, ?, ?, ?, ?, ?)",
            (kind, ref, fld, lang, value, src_hash(it.base)))
        saved += 1
    await ctx.reload()
    await ctx.log("tr.import", f"{saved} шт.")
    ctx.notice = f"✅ Загружено переводов: {saved}"
    if errors:
        ctx.notice += "\n⚠️ Пропущено:\n" + "\n".join(escape(e) for e in errors[:10])
    return "a:langs"
