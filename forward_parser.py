def extract_chat_id_from_forward(message) -> str | None:
    """
    Определяет chat_id исходного чата/канала/группы по пересланному сообщению.
    Работает, если у сообщения проставлен forward_origin с указанием чата
    (для этого бот должен состоять в этом чате как администратор, либо
    пересылка должна раскрывать источник).
    """
    origin = message.forward_origin
    if origin is None:
        return None

    # aiogram 3.x: MessageOriginChannel / MessageOriginChat содержат поле chat
    chat = getattr(origin, "chat", None)
    if chat is not None:
        if chat.username:
            return f"@{chat.username}"
        return str(chat.id)

    return None


def parse_chat_source(message) -> str | None:
    """
    Универсальный разбор источника чата/канала: администратор может
    прислать ЛЮБОЕ из трёх — публичную ссылку, Chat ID (-100... или
    @username), либо просто переслать сообщение из нужного чата.
    Бот сам определяет, что именно ему прислали.

    Если чат публичный — возвращается @username.
    Если приватный — возвращается числовой chat_id (только через
    пересланное сообщение, т.к. у приватных чатов нет публичной ссылки).
    """
    # 1) пересланное сообщение — работает и с приватными, и с публичными чатами
    forwarded = extract_chat_id_from_forward(message)
    if forwarded:
        return forwarded

    raw = (message.text or "").strip()
    if not raw:
        return None

    # 2) публичная ссылка вида https://t.me/username или t.me/username
    if "t.me/" in raw:
        username = raw.split("t.me/")[-1].split("?")[0].strip("/")
        if username and not username.startswith("+") and "joinchat" not in raw:
            return f"@{username}"
        return None

    # 3) @username
    if raw.startswith("@"):
        return raw

    # 4) числовой Chat ID, например -1001234567890
    cleaned = raw.replace(" ", "")
    if cleaned.lstrip("-").isdigit():
        return cleaned

    return None
