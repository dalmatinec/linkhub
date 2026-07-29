import sqlite3
from datetime import datetime

DB_PATH = "database/database.db"


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""CREATE TABLE IF NOT EXISTS users (
        telegram_id INTEGER PRIMARY KEY,
        username TEXT,
        first_name TEXT,
        push_enabled INTEGER DEFAULT 1,
        language TEXT DEFAULT 'ru',
        verified INTEGER DEFAULT 0,
        created_at TEXT
    )""")

    cur.execute("""CREATE TABLE IF NOT EXISTS admins (
        telegram_id INTEGER PRIMARY KEY
    )""")

    cur.execute("""CREATE TABLE IF NOT EXISTS start_message (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        text TEXT,
        photo_file_id TEXT,
        icon_custom_emoji_id TEXT,
        link_duration_minutes INTEGER DEFAULT 30,
        buttons_per_row INTEGER DEFAULT 1
    )""")

    # миграция для уже существующих БД, созданных до появления buttons_per_row
    cur.execute("PRAGMA table_info(start_message)")
    existing_cols = [row["name"] for row in cur.fetchall()]
    if "buttons_per_row" not in existing_cols:
        cur.execute("ALTER TABLE start_message ADD COLUMN buttons_per_row INTEGER DEFAULT 1")

    cur.execute("""CREATE TABLE IF NOT EXISTS buttons (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT,
        type TEXT,               -- 'direct' | 'generated'
        url TEXT,                 -- для type='direct'
        chat_id TEXT,              -- для type='generated'
        style TEXT DEFAULT 'primary',   -- 'primary' | 'success' | 'danger'
        icon_custom_emoji_id TEXT,
        position INTEGER,
        created_at TEXT
    )""")

    cur.execute("""CREATE TABLE IF NOT EXISTS broadcasts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        total INTEGER,
        sent INTEGER,
        failed INTEGER,
        duration_seconds INTEGER,
        created_at TEXT
    )""")

    cur.execute("SELECT COUNT(*) AS c FROM start_message")
    if cur.fetchone()["c"] == 0:
        cur.execute(
            "INSERT INTO start_message (id, text, photo_file_id, icon_custom_emoji_id, link_duration_minutes) "
            "VALUES (1, NULL, NULL, NULL, 30)"
        )

    conn.commit()
    conn.close()


# ---------- users ----------

def add_user(telegram_id: int, username: str, first_name: str):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT telegram_id FROM users WHERE telegram_id = ?", (telegram_id,))
    if not cur.fetchone():
        cur.execute(
            "INSERT INTO users (telegram_id, username, first_name, push_enabled, language, verified, created_at) "
            "VALUES (?, ?, ?, 1, 'ru', 0, ?)",
            (telegram_id, username, first_name, datetime.now().isoformat())
        )
        conn.commit()
    conn.close()


def get_user(telegram_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,))
    row = cur.fetchone()
    conn.close()
    return row


def set_verified(telegram_id: int):
    conn = get_conn()
    conn.execute("UPDATE users SET verified = 1 WHERE telegram_id = ?", (telegram_id,))
    conn.commit()
    conn.close()


def is_verified(telegram_id: int) -> bool:
    user = get_user(telegram_id)
    return bool(user and user["verified"])


def set_push(telegram_id: int, enabled: bool):
    conn = get_conn()
    conn.execute("UPDATE users SET push_enabled = ? WHERE telegram_id = ?", (int(enabled), telegram_id))
    conn.commit()
    conn.close()


def get_all_users(push_only: bool = False):
    conn = get_conn()
    cur = conn.cursor()
    if push_only:
        cur.execute("SELECT * FROM users WHERE push_enabled = 1")
    else:
        cur.execute("SELECT * FROM users")
    rows = cur.fetchall()
    conn.close()
    return rows


def count_users() -> int:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) AS c FROM users")
    c = cur.fetchone()["c"]
    conn.close()
    return c


def count_push(enabled: bool) -> int:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) AS c FROM users WHERE push_enabled = ?", (int(enabled),))
    c = cur.fetchone()["c"]
    conn.close()
    return c


def get_launch_date() -> str:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT created_at FROM users ORDER BY created_at ASC LIMIT 1")
    row = cur.fetchone()
    conn.close()
    if row:
        return row["created_at"][:10]
    return "—"


# ---------- admins ----------

def add_admin(telegram_id: int):
    conn = get_conn()
    conn.execute("INSERT OR IGNORE INTO admins (telegram_id) VALUES (?)", (telegram_id,))
    conn.commit()
    conn.close()


def remove_admin(telegram_id: int):
    conn = get_conn()
    conn.execute("DELETE FROM admins WHERE telegram_id = ?", (telegram_id,))
    conn.commit()
    conn.close()


def is_admin(telegram_id: int) -> bool:
    from config import SUPER_ADMIN_ID
    if telegram_id == SUPER_ADMIN_ID:
        return True
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT telegram_id FROM admins WHERE telegram_id = ?", (telegram_id,))
    row = cur.fetchone()
    conn.close()
    return bool(row)


def list_admins():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT telegram_id FROM admins")
    rows = [r["telegram_id"] for r in cur.fetchall()]
    conn.close()
    return rows


def count_admins() -> int:
    from config import SUPER_ADMIN_ID
    return len(list_admins()) + 1  # +1 за Super Admin


# ---------- start_message ----------

def get_start_message():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM start_message WHERE id = 1")
    row = cur.fetchone()
    conn.close()
    return row


def update_start_message(**fields):
    if not fields:
        return
    conn = get_conn()
    cols = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values())
    conn.execute(f"UPDATE start_message SET {cols} WHERE id = 1", values)
    conn.commit()
    conn.close()


# ---------- buttons ----------

def get_buttons():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM buttons ORDER BY position ASC, id ASC")
    rows = cur.fetchall()
    conn.close()
    return rows


def get_button(button_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM buttons WHERE id = ?", (button_id,))
    row = cur.fetchone()
    conn.close()
    return row


def add_button(title, type_, url, chat_id, style, icon_custom_emoji_id):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT COALESCE(MAX(position), 0) AS m FROM buttons")
    next_pos = cur.fetchone()["m"] + 1
    cur.execute(
        "INSERT INTO buttons (title, type, url, chat_id, style, icon_custom_emoji_id, position, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (title, type_, url, chat_id, style, icon_custom_emoji_id, next_pos, datetime.now().isoformat())
    )
    conn.commit()
    new_id = cur.lastrowid
    conn.close()
    return new_id


def update_button(button_id: int, **fields):
    if not fields:
        return
    conn = get_conn()
    cols = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [button_id]
    conn.execute(f"UPDATE buttons SET {cols} WHERE id = ?", values)
    conn.commit()
    conn.close()


def delete_button(button_id: int):
    conn = get_conn()
    conn.execute("DELETE FROM buttons WHERE id = ?", (button_id,))
    conn.commit()
    conn.close()


def move_button(button_id: int, direction: str):
    """direction: 'up' или 'down'. Меняет местами позиции соседних кнопок,
    чтобы администратор мог управлять порядком отображения."""
    buttons = get_buttons()
    ids = [b["id"] for b in buttons]
    if button_id not in ids:
        return
    idx = ids.index(button_id)
    if direction == "up" and idx > 0:
        other_idx = idx - 1
    elif direction == "down" and idx < len(buttons) - 1:
        other_idx = idx + 1
    else:
        return

    b1, b2 = buttons[idx], buttons[other_idx]
    conn = get_conn()
    conn.execute("UPDATE buttons SET position = ? WHERE id = ?", (b2["position"], b1["id"]))
    conn.execute("UPDATE buttons SET position = ? WHERE id = ?", (b1["position"], b2["id"]))
    conn.commit()
    conn.close()


# ---------- настройки отображения ----------

def get_buttons_per_row() -> int:
    sm = get_start_message()
    value = sm["buttons_per_row"] if sm and sm["buttons_per_row"] else 1
    return 2 if value == 2 else 1


def set_buttons_per_row(count: int):
    update_start_message(buttons_per_row=2 if count == 2 else 1)


# ---------- broadcasts ----------

def add_broadcast_record(total: int, sent: int, failed: int, duration_seconds: int):
    conn = get_conn()
    conn.execute(
        "INSERT INTO broadcasts (total, sent, failed, duration_seconds, created_at) VALUES (?, ?, ?, ?, ?)",
        (total, sent, failed, duration_seconds, datetime.now().isoformat())
    )
    conn.commit()
    conn.close()


def count_broadcasts() -> int:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) AS c FROM broadcasts")
    c = cur.fetchone()["c"]
    conn.close()
    return c
