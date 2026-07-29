def extract_custom_emoji_id(message) -> str | None:
    """
    Ищет premium (custom) эмодзи в тексте или подписи сообщения
    и возвращает его custom_emoji_id. Админу не нужно знать ID вручную —
    он просто отправляет эмодзи, бот сам его находит.
    """
    entities = message.entities or message.caption_entities or []
    for entity in entities:
        if entity.type == "custom_emoji":
            return entity.custom_emoji_id
    return None
