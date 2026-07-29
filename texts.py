import json

TEXTS_FILE = "texts.json"


def load_texts() -> dict:
    with open(TEXTS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def get_text(path: str, default: str = "", **kwargs) -> str:
    """
    Достаёт текст по пути вида 'links.direct_ready' из texts.json
    и подставляет {переменные}, если они переданы.
    """
    data = load_texts()
    value = data
    for part in path.split("."):
        if isinstance(value, dict) and part in value:
            value = value[part]
        else:
            return default
    if not isinstance(value, str):
        return default
    if kwargs:
        try:
            return value.format(**kwargs)
        except (KeyError, IndexError):
            return value
    return value
