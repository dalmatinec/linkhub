"""Журнал действий админов: понятные русские описания вместо служебных ключей."""
from html import escape

from ...app import App

ACTION_NAMES = {
    "shop.create": "создал магазин", "shop.delete": "удалил магазин", "shop.publish": "опубликовал магазин",
    "shop.hide": "скрыл магазин", "shop.tag_on": "поставил метку", "shop.tag_off": "снял метку",
    "shop.tag_expired": "срок метки истёк", "shop.tag_expiry": "изменил срок метки", "shop.contacts": "изменил контакты",
    "shop.verified": "переключил «Проверенный»", "shop.categories": "изменил категории", "menu.create": "добавил кнопку меню", "menu.delete": "удалил кнопку меню",
    "menu.toggle": "скрыл/показал кнопку меню", "city.create": "добавил города", "city.delete": "удалил город",
    "tag.create": "создал метку", "tag.delete": "удалил метку", "user.ban": "забанил", "user.unban": "разбанил",
    "admin.add": "добавил админа", "admin.remove": "снял админа", "admin.perms": "изменил права админа",
    "broadcast.start": "запустил рассылку", "backup.create": "сделал бэкап", "backup.restore": "восстановил из бэкапа",
    "settings": "изменил настройку", "report.done": "закрыл жалобу",
    "cat.create": "создал категорию", "cat.delete": "удалил категорию", "appl.accept": "одобрил заявку",
    "appl.reject": "отклонил заявку", "appl.reply": "ответил на заявку", "field.create": "добавил вопрос анкеты",
    "field.delete": "удалил вопрос анкеты", "tr.import": "загрузил переводы", "tr.edit": "изменил перевод",
    "lang.toggle": "включил/выключил язык", "logchat.set": "подключил канал логов",
}
# универсальные правки: «<что>.<поле>»
OBJECT_NAMES = {"item": "кнопка меню", "text": "текст", "btn": "системная кнопка", "city": "город", "shop": "магазин",
                "tag": "метка", "cat": "категория", "field": "вопрос анкеты"}
FIELD_NAMES = {"label": "изменил текст кнопки", "html": "изменил текст", "media": "изменил медиа",
               "media_removed": "убрал медиа"}


def describe(app: App, action: str, details: str) -> str:
    """Понятная строка журнала вместо служебных ключей."""
    from .content import BUTTON_NAMES, TEXT_NAMES
    cat = app.catalog
    if action in ACTION_NAMES:
        return f"{ACTION_NAMES[action]} {escape(details[:60])}"
    obj, _, field = action.partition(".")
    what = FIELD_NAMES.get(field, field)
    key = details.split(":", 1)[0]
    name = {
        "text": lambda: TEXT_NAMES.get(key, "текст"),
        "btn": lambda: BUTTON_NAMES.get(key, "кнопка"),
        "shop": lambda: cat.shops[int(key)].label if key.isdigit() and int(key) in cat.shops else f"#{key}",
        "item": lambda: (cat.menu[int(key)].label or "главное меню") if key.isdigit() and int(key) in cat.menu else f"#{key}",
        "city": lambda: cat.cities[int(key)].label if key.isdigit() and int(key) in cat.cities else f"#{key}",
        "tag": lambda: cat.tags[int(key)].label if key.isdigit() and int(key) in cat.tags else f"#{key}",
        "cat": lambda: cat.categories[int(key)].label if key.isdigit() and int(key) in cat.categories else f"#{key}",
        "field": lambda: next((f.label for f in cat.fields if str(f.id) == key), f"#{key}"),
    }.get(obj, lambda: details)()
    return f"{what} — {OBJECT_NAMES.get(obj, obj)} «{escape(str(name)[:40])}»"
