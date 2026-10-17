"""Описание видов каталога и полей для мастера добавления в админке."""

DEV_CATS = {
    "bots": "🤖 Telegram боты",
    "sites": "🌐 Сайты",
    "miniapp": "📱 Mini App",
    "servers": "🖥 Сервера и DevOps",
    "other": "🧩 Другое",
}

KIND_NAMES = {
    "gift": "🎁 Подарки",
    "uname": "💎 Готовые юзеры",
    "service": "🛠 Услуги",
    "portfolio": "🖼 Портфолио",
}

# (поле, вопрос, тип, можно пропустить)
FIELDS: dict[str, list[tuple[str, str, str, bool]]] = {
    "gift": [
        ("title", "Название подарка, например «Plush Pepe #1234»", "text", False),
        ("price", "Цена в тенге", "number", False),
        ("photo", "Фото подарка", "photo", True),
        ("link", "Ссылка на подарок (t.me/nft/...)", "url", True),
        ("description", "Описание: модель, фон, редкость", "text", True),
    ],
    "uname": [
        ("title", "Юзернейм (без @)", "username", False),
        ("cost_ton", "Себестоимость в TON (сколько заплатили)", "number", False),
        ("markup", "Наценка множителем, например 2 (если пропустить, берётся из настроек)", "number", True),
        ("description", "Описание для покупателя", "text", True),
    ],
    "service": [
        ("category", "Категория услуги", "choice", False),
        ("title", "Название услуги, например «Бот магазин под ключ»", "text", False),
        ("price_text", "Цена или варианты, например «от 50 000 ₸» (можно несколько строк)", "text", False),
        ("description", "Что входит в услугу", "text", True),
    ],
    "portfolio": [
        ("title", "Название работы", "text", False),
        ("description", "Описание: что сделано, стек, результат", "text", True),
        ("photo", "Скриншот или обложка", "photo", True),
        ("link", "Ссылка (бот, сайт, канал)", "url", True),
    ],
}

FIELD_NAMES = {
    "title": "Название",
    "price": "Цена, ₸",
    "photo": "Фото",
    "link": "Ссылка",
    "description": "Описание",
    "cost_ton": "Себестоимость, TON",
    "markup": "Наценка, x",
    "category": "Категория",
    "price_text": "Цена (текст)",
}

BUDGETS = ["до 50 000 ₸", "50 000 - 150 000 ₸", "150 000 - 500 000 ₸", "от 500 000 ₸", "Пока не знаю"]
DEADLINES = ["Срочно", "1-2 недели", "До месяца", "Не горит"]
