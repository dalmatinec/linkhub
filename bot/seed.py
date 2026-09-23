"""Начальные данные. Структура (меню, города, метки) заливается один раз — в пустую базу.
Настройки, тексты и системные кнопки дозаливаются при каждом старте, если ключа ещё нет:
так новые ключи из обновлений появляются сами и не затирают правки из админки."""
import json
import time
from pathlib import Path

from .db import Database

SEED_PATH = Path(__file__).with_name("seed.json")
LEGACY_PATH = Path(__file__).with_name("seed_legacy.json")  # прежние стандартные тексты
TEXTS_REV = "texts_v3"  # поменяли стандартные тексты — увеличить номер, чтобы нетронутые обновились в базе


async def apply_seed(db: Database) -> None:
    seed = json.loads(SEED_PATH.read_text(encoding="utf-8"))

    await db.executemany(
        "INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)",
        ((k, json.dumps(v)) for k, v in seed["settings"].items()),
    )
    await db.executemany(
        "INSERT OR IGNORE INTO texts(key, html) VALUES (?, ?)", seed["texts"].items()
    )
    await db.executemany(
        "INSERT OR IGNORE INTO buttons(key, label, icon, style) VALUES (?, ?, ?, ?)",
        ((k, b["label"], b.get("icon"), b.get("style")) for k, b in seed["buttons"].items()),
    )

    # Наборы, появившиеся в обновлениях, заливаются один раз (флаг в settings), даже в старую базу
    for flag, table, rows, sql in (
        ("seed_categories", "categories", [(n, i) for i, n in enumerate(seed["categories"])],
         "INSERT INTO categories(label, position) VALUES (?, ?)"),
        ("seed_app_fields", "app_fields",
         [(f["label"], f["html"], f["kind"], f["role"], f["required"], i) for i, f in enumerate(seed["app_fields"])],
         "INSERT INTO app_fields(label, html, kind, role, required, position) VALUES (?, ?, ?, ?, ?, ?)"),
    ):
        if await db.fetchval("SELECT 1 FROM settings WHERE key = ?", (flag,)):
            continue
        if not await db.fetchval(f"SELECT COUNT(*) FROM {table}"):
            await db.executemany(sql, rows)
        await db.execute("INSERT INTO settings(key, value) VALUES (?, '1')", (flag,))

    if await db.fetchval("SELECT COUNT(*) FROM menu_items"):
        await refresh_default_texts(db, seed)
        await upgrade_layout(db)
        return

    await db.executemany(
        "INSERT INTO tags(id, label, position) VALUES (?, ?, ?)",
        ((t["id"], t["label"], t["position"]) for t in seed["tags"]),
    )
    root = seed["menu"]
    root_id = await db.execute(
        "INSERT INTO menu_items(parent_id, kind, label, html, is_system) VALUES (NULL, 'menu', 'Главное меню', ?, 1)",
        (root["html"],),
    )
    await _insert_items(db, root_id, root["children"])
    cities = [(name, 1, pos) for pos, name in enumerate(seed["cities"]["main"])]
    cities += [(name, 0, pos) for pos, name in enumerate(seed["cities"]["other"])]
    await db.executemany("INSERT INTO cities(label, is_main, position) VALUES (?, ?, ?)", cities)
    for flag in ("seeded_at", "layout_v2", TEXTS_REV):
        await db.execute("INSERT OR REPLACE INTO settings(key, value) VALUES (?, ?)", (flag, str(int(time.time()))))


async def _insert_items(db: Database, parent_id: int, items: list[dict]) -> None:
    for pos, item in enumerate(items):
        item_id = await db.execute(
            "INSERT INTO menu_items(parent_id, kind, payload, label, icon, style, html, row, position)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (parent_id, item["kind"], item.get("payload"), item["label"], item.get("icon"),
             item.get("style"), item.get("html", ""), item.get("row", pos), pos),
        )
        if item.get("children"):
            await _insert_items(db, item_id, item["children"])


async def refresh_default_texts(db: Database, seed: dict) -> None:
    """Один раз: стандартные тексты прошлых версий меняются на новые. Тексты, которые правил админ, не трогаем."""
    if await db.fetchval("SELECT 1 FROM settings WHERE key = ?", (TEXTS_REV,)):
        return
    legacy = json.loads(LEGACY_PATH.read_text(encoding="utf-8"))
    for key, olds in legacy["texts"].items():
        new = seed["texts"].get(key)
        if new is not None:
            for old in olds:
                await db.execute("UPDATE texts SET html = ? WHERE key = ? AND html = ?", (new, key, old))
    for key, olds in legacy["buttons"].items():
        new = seed["buttons"].get(key, {}).get("label")
        if new is not None:
            for old in olds:
                await db.execute("UPDATE buttons SET label = ? WHERE key = ? AND label = ?", (new, key, old))
    new_fields = {f["label"]: f["html"] for f in seed["app_fields"]}
    for label, olds in legacy["fields"].items():
        if label in new_fields:
            for old in olds:
                await db.execute("UPDATE app_fields SET html = ? WHERE label = ? AND html = ?",
                                 (new_fields[label], label, old))
    for old in legacy["root"]:
        await db.execute("UPDATE menu_items SET html = ? WHERE parent_id IS NULL AND html = ?",
                         (seed["menu"]["html"], old))
    await db.execute("INSERT OR REPLACE INTO settings(key, value) VALUES (?, ?)", (TEXTS_REV, str(int(time.time()))))


async def upgrade_layout(db: Database) -> None:
    """Один раз: «Выбрать город» в главном меню становится блоком городов,
    «Разместить магазин» и «Язык» переезжают в подменю «☰ Ещё»."""
    if await db.fetchval("SELECT 1 FROM settings WHERE key = 'layout_v2'"):
        return
    root = await db.fetchval("SELECT id FROM menu_items WHERE parent_id IS NULL ORDER BY is_system DESC, id LIMIT 1")
    if root:
        await db.execute("UPDATE menu_items SET kind = 'city_block' WHERE parent_id = ? AND kind = 'cities'", (root,))
        movable = await db.fetchall(
            "SELECT id FROM menu_items WHERE parent_id = ? AND kind IN ('apply', 'language') ORDER BY row, position",
            (root,))
        if movable:
            row = await db.fetchval("SELECT COALESCE(MAX(row), -1) + 1 FROM menu_items WHERE parent_id = ?", (root,))
            more = await db.execute(
                "INSERT INTO menu_items(parent_id, kind, label, html, row, position) VALUES (?, 'menu', '☰ Ещё', ?, ?, 0)",
                (root, "☰ <b>Ещё</b>", row))
            await db.executemany("UPDATE menu_items SET parent_id = ?, row = ?, position = 0 WHERE id = ?",
                                 ((more, i, r["id"]) for i, r in enumerate(movable)))
        # убираем пустые ряды в главном меню
        rows = await db.fetchall("SELECT id, row FROM menu_items WHERE parent_id = ? ORDER BY row, position, id", (root,))
        mapping: dict[int, int] = {}
        counters: dict[int, int] = {}
        updates = []
        for r in rows:
            new_row = mapping.setdefault(r["row"], len(mapping))
            updates.append((new_row, counters.get(new_row, 0), r["id"]))
            counters[new_row] = counters.get(new_row, 0) + 1
        await db.executemany("UPDATE menu_items SET row = ?, position = ? WHERE id = ?", updates)
    await db.execute("INSERT OR REPLACE INTO settings(key, value) VALUES ('layout_v2', ?)", (str(int(time.time())),))
