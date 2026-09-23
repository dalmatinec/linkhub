"""Начальные данные. Структура (меню, города, метки) заливается один раз — в пустую базу.
Настройки, тексты и системные кнопки дозаливаются при каждом старте, если ключа ещё нет:
так новые ключи из обновлений появляются сами и не затирают правки из админки."""
import json
import time
from pathlib import Path

from .db import Database

SEED_PATH = Path(__file__).with_name("seed.json")


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

    if await db.fetchval("SELECT COUNT(*) FROM menu_items"):
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
    for pos, item in enumerate(root["children"]):
        await db.execute(
            "INSERT INTO menu_items(parent_id, kind, payload, label, icon, style, html, row, position)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                root_id, item["kind"], item.get("payload"), item["label"], item.get("icon"),
                item.get("style"), item.get("html", ""), item.get("row", pos), pos,
            ),
        )
    cities = [(name, 1, pos) for pos, name in enumerate(seed["cities"]["main"])]
    cities += [(name, 0, pos) for pos, name in enumerate(seed["cities"]["other"])]
    await db.executemany("INSERT INTO cities(label, is_main, position) VALUES (?, ?, ?)", cities)
    await db.execute(
        "INSERT OR REPLACE INTO settings(key, value) VALUES ('seeded_at', ?)", (str(int(time.time())),)
    )
