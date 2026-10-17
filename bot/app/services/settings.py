"""Настройки бота: хранятся в таблице settings, держатся в памяти (читаются без запросов к базе)."""

from aiogram.utils.formatting import Bold, Text
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import config
from ..db.models import Setting
from ..utils import Rich, entities_from_store

DEFAULTS: dict = {
    "brand": config.brand,
    "star_tiers": [[50, 9.5], [250, 9.2], [1000, 8.9], [5000, 8.6]],
    "star_presets": [50, 100, 250, 500, 1000, 2500, 5000],
    "sla_stars": "до 3 часов",
    "sla_exchange": "от 5 до 30 минут",
    "sla_gifts": "до 3 часов",
    "ton_kzt": 0,
    "uname_markup": 2,
    "uname_hold_days": 7,
    "uname_auction_days": 7,
    "work_enabled": True,
    "work_from": "10:00",
    "work_to": "02:00",
    "ref_percent": 5,
    "ref_base": "profit",
    "channel_link": "",
    "reviews_link": "",
    "site_url": config.site_url,
    "post_mode": "account" if config.poster_enabled else "bot",
    "backup_time": config.backup_time,
    "backup_last_day": "",
    "backup_last": {},
}


def _default_rich(key: str) -> Rich:
    brand = get("brand")
    if key == "welcome":
        text, ents = Text(
            "👋 Добро пожаловать в ", Bold(brand), "!\n\n",
            "⭐ Звёзды Telegram оптом и в розницу\n",
            "🎁 NFT подарки\n",
            "💎 Красивые юзернеймы\n",
            "💱 Обмен\n",
            "🛠 Разработка ботов, сайтов и серверов\n\n",
            "Выберите раздел ниже 👇",
        ).render()
    elif key == "pay_info":
        text, ents = Text(
            Bold("💳 Оплата"), "\n",
            "Менеджер пришлёт реквизиты в этот чат. После оплаты нажмите «Я оплатил».",
        ).render()
    elif key == "after_hours":
        text, ents = Text(
            "🌙 Сейчас нерабочее время.\n",
            "Сообщение принято, менеджер ответит с ", Bold(get("work_from")), ".",
        ).render()
    elif key == "rates_template":
        text, ents = Text(
            Bold("💱 Курсы на {date}"), "\n\n", "{rates}", "\n\n",
            "⭐ Звёзды от {stars_min}\n",
            "⚡ Обмен {sla_exchange}\n\n",
            "Заказать: {bot}",
        ).render()
    else:
        return Rich("")
    return Rich(text, ents or None)


_cache: dict = {}


async def load(session_maker) -> None:
    async with session_maker() as session:
        rows = (await session.execute(select(Setting))).scalars().all()
        _cache.clear()
        _cache.update({r.key: r.value for r in rows})


def get(key: str):
    if key in _cache:
        return _cache[key]
    return DEFAULTS.get(key)


async def put(session: AsyncSession, key: str, value) -> None:
    await session.merge(Setting(key=key, value=value))
    _cache[key] = value


async def reset(session: AsyncSession, key: str) -> None:
    row = await session.get(Setting, key)
    if row is not None:
        await session.delete(row)
    _cache.pop(key, None)


def rich(key: str) -> Rich:
    stored = _cache.get(key)
    if isinstance(stored, dict) and stored.get("text"):
        return Rich(stored["text"], entities_from_store(stored.get("entities")))
    return _default_rich(key)


def rich_raw(key: str) -> tuple[str, list[dict]]:
    """Текст и entities в виде словарей (для шаблонов и постера)."""
    stored = _cache.get(key)
    if isinstance(stored, dict) and stored.get("text"):
        return stored["text"], list(stored.get("entities") or [])
    r = _default_rich(key)
    return r.text, [e.model_dump(exclude_none=True) for e in (r.entities or [])]


def star_tiers() -> list[tuple[int, float]]:
    tiers = []
    for row in get("star_tiers") or []:
        try:
            tiers.append((int(row[0]), float(row[1])))
        except (TypeError, ValueError, IndexError):
            continue
    tiers.sort()
    return tiers or [(50, 9.5)]
