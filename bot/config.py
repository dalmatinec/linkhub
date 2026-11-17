"""Настройки из файла .env. Всё, что меняется без правки кода, лежит здесь."""

import os
from pathlib import Path
from zoneinfo import ZoneInfo


def _load_env(path: Path) -> None:
    """Простая загрузка .env без лишних библиотек. Уже заданные переменные не трогает."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


ROOT = Path(__file__).resolve().parent.parent
# у копий white label свой файл настроек: LINKHUB_ENV=/opt/linkhub/instances/<имя>/.env
_load_env(Path(os.getenv("LINKHUB_ENV") or ROOT / ".env"))


def _float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except ValueError:
        return default


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except ValueError:
        return default


# Telegram
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
OWNER_IDS = {int(x) for x in os.getenv("OWNER_IDS", "").replace(" ", "").split(",") if x.lstrip("-").isdigit()}

# Нейросеть: любой сервис с API в формате OpenAI. Адрес и модель меняются в .env
AI_BASE_URL = os.getenv("AI_BASE_URL", "https://api.deepseek.com").rstrip("/")
AI_API_KEY = os.getenv("AI_API_KEY", "")
AI_MODEL = os.getenv("AI_MODEL", "deepseek-chat")
AI_TIMEOUT = _float("AI_TIMEOUT", 40)
AI_MAX_TOKENS = _int("AI_MAX_TOKENS", 160)
AI_TEMPERATURE = _float("AI_TEMPERATURE", 1.1)

# Цены модели в долларах за 1 млн токенов, нужны только для подсчёта расхода (платишь ты по тарифу сервиса).
# По умолчанию тариф DeepSeek Flash в обычные часы; в часы пик всё умножается на PRICE_PEAK_X.
PRICE_IN = _float("PRICE_IN", 0.15)        # вход, которого нет в кэше
PRICE_OUT = _float("PRICE_OUT", 0.60)      # ответ нейросети
PRICE_CACHE = _float("PRICE_CACHE", 0.003)  # вход из кэша: характер и правила, которые не меняются
if (PRICE_IN, PRICE_OUT) == (0.30, 1.20):  # старые цифры из прежнего .env.example: это цены пика, считаем по новым
    PRICE_IN, PRICE_OUT = 0.15, 0.60
PRICE_PEAK_X = _float("PRICE_PEAK_X", 2.0)
# часы пика по UTC (пн-пт), у DeepSeek 01:00-04:00 и 06:00-10:00, это 06-09 и 11-15 по Алматы
PEAK_HOURS_UTC = os.getenv("PEAK_HOURS_UTC", "1-4,6-10")
# Сколько долларов в сутки можно потратить. Кончились, бот отвечает фразами из базы.
DAILY_LIMIT_USD = _float("DAILY_LIMIT_USD", 0.20)

# Сколько последних сообщений чата видит нейросеть
CONTEXT_MESSAGES = _int("CONTEXT_MESSAGES", 20)
# Сколько сообщений чата хранить в базе (для памяти о юзерах нужно больше, чем контекст)
HISTORY_KEEP = _int("HISTORY_KEEP", 2000)
# Через сколько сообщений юзера обновлять заметки о нём (0 = не обновлять)
MEMORY_EVERY = _int("MEMORY_EVERY", 50)   # заметку о человеке обновляем раз в столько его сообщений
MEMORY_FIRST = _int("MEMORY_FIRST", 20)   # первую заметку о новичке пишем пораньше, чтобы бот быстрее его узнал

TZ = ZoneInfo(os.getenv("TZ_NAME", "Asia/Almaty"))
DATA_DIR = ROOT / os.getenv("DATA_DIR", "data")
DB_PATH = DATA_DIR / "bot.db"
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# Значения по умолчанию для нового чата (потом меняются в /admin)
# имя бота в новых чатах. Пусто: берётся имя из профиля бота в Telegram (BotFather → /setname).
# «Марат» было старым значением по умолчанию и тоже считается пустым
DEFAULT_NAME = "" if os.getenv("DEFAULT_NAME", "") == "Марат" else os.getenv("DEFAULT_NAME", "")
LEGACY_NAME = "Марат"
DEFAULT_PERSONA = os.getenv(
    "DEFAULT_PERSONA",
    "свой пацан из чата, дерзкий и весёлый, любит подколоть, но не злой. "
    "отвечает коротко, по-простому, со сленгом",
)
DEFAULT_TOPIC = os.getenv("DEFAULT_TOPIC", "общение обо всём, болтовня, приколы")
DEFAULT_CHANCE = _float("DEFAULT_CHANCE", 0.04)      # шанс влезть в чужой разговор
DEFAULT_AI_SHARE = _float("DEFAULT_AI_SHARE", 0.30)  # доля таких влезаний через ИИ
DEFAULT_COOLDOWN = _int("DEFAULT_COOLDOWN", 90)      # пауза между самовольными влезаниями, сек


# main: твой основной бот (продаёт рекламу, аренду и white label). client: копия для клиента
EDITION = os.getenv("EDITION", "main")
IS_MAIN = EDITION == "main"
INSTANCES_DIR = Path(os.getenv("INSTANCES_DIR", str(ROOT / "instances")))
# у копии: имя в папке instances, по нему она находит свою лицензию
INSTANCE_NAME = os.getenv("INSTANCE_NAME", "")

# Оплата USDT в сети TON: адрес кошелька для приёма и бесплатный ключ toncenter
PAY_TON_ADDRESS = os.getenv("PAY_TON_ADDRESS", "")
TONCENTER_API_KEY = os.getenv("TONCENTER_API_KEY", "")
TONCENTER_URL = os.getenv("TONCENTER_URL", "https://toncenter.com/api/v3").rstrip("/")
USDT_MASTER = os.getenv("USDT_MASTER", "EQCxE6mUtQJKFnGfaROTKOt1lZbDiiX1kCixRv7Nw2Id_sDs")
# USDT в сети TRON (TRC20): адрес T... и бесплатный ключ TronGrid (можно без ключа)
PAY_TRON_ADDRESS = os.getenv("PAY_TRON_ADDRESS", "")
TRONGRID_API_KEY = os.getenv("TRONGRID_API_KEY", "")
TRONGRID_URL = os.getenv("TRONGRID_URL", "https://api.trongrid.io").rstrip("/")
TRON_USDT_CONTRACT = os.getenv("TRON_USDT_CONTRACT", "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t")
# канал для формата «закреп в канале» (бот должен быть админом с правом закреплять), например -1001234567890
AD_CHANNEL_ID = int(os.getenv("AD_CHANNEL_ID", "0") or 0)
# сколько часов ждать одобрения чата, потом бот сам выходит
APPROVAL_HOURS = _int("APPROVAL_HOURS", 24)
TRIAL_DAYS = _int("TRIAL_DAYS", 3)
# сайт с описанием бота и командами: кнопки в боте ведут туда (у копий клиентов по умолчанию нет)
SITE_URL = os.getenv("SITE_URL", "https://satpaev.ceo" if IS_MAIN else "").strip().rstrip("/")

# Создатель бота: бот его уважает, хвалит по-своему и советует заказывать у него проекты.
# Узнаёт его ТОЛЬКО по Telegram ID (по умолчанию у основного бота это OWNER_IDS), не по имени:
# любой может подписаться чужим именем. CREATOR=0 отключает.
CREATOR_ON = os.getenv("CREATOR", "1" if IS_MAIN else "0").strip() not in ("0", "", "no", "off")
CREATOR_NAME = os.getenv("CREATOR_NAME", "").strip()   # как бот его называет; пусто: просто создатель
CREATOR_IDS = ({int(x) for x in os.getenv("CREATOR_IDS", "").replace(" ", "").split(",") if x.lstrip("-").isdigit()}
               or set(OWNER_IDS)) if CREATOR_ON else set()
CREATOR_CONTACT = os.getenv("CREATOR_CONTACT", "").strip()  # например @username, иначе возьмём юзернейм из базы


# Связь с модератором (dalmatinec/baxi-guard). Оба бота слушают только 127.0.0.1, ключ одинаковый в .env обоих.
# Пусто в BAXI_API_KEY: API Бакси не запускается, к модератору не ходим (копиям клиентов так и надо).
BAXI_API_PORT = _int("BAXI_API_PORT", 8710)
GUARD_API_URL = os.getenv("GUARD_API_URL", "").strip().rstrip("/")
BAXI_API_KEY = os.getenv("BAXI_API_KEY", "").strip()


def check() -> None:
    if not BOT_TOKEN:
        raise SystemExit("В .env не задан BOT_TOKEN")
    if not OWNER_IDS:
        raise SystemExit("В .env не задан OWNER_IDS (твой Telegram ID)")
