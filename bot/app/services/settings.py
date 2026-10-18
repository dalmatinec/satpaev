"""Настройки бота: хранятся в таблице settings, держатся в памяти (читаются без запросов к базе)."""

from html import escape

from aiogram.utils.formatting import Bold, Text
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import config
from ..db.models import Setting
from ..texts import BUTTONS, MENU_KEYS, SCREENS, TEXTS, fill
from ..utils import Rich, entities_from_store

DEFAULTS: dict = {
    "brand": config.brand,
    "star_tiers": [[500, 12], [1000, 11.5], [5000, 11]],
    "star_presets": [500, 1000, 2500, 5000, 10000],
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
    "sub_mode": "required",
    "sub_channels": [{"chat": "@newssatbox", "url": "https://t.me/newssatbox", "title": "newssatbox"}],
}


def _default_rich(key: str) -> Rich:
    if key == "rates_template":
        text, ents = Text(
            Bold("💱 Курсы на {date}"), "\n\n", "{rates}", "\n\n",
            "⭐ Звёзды от {stars_min}\n",
            "⚡ Обмен {sla_exchange}\n\n",
            "Заказать: {bot}",
        ).render()
        return Rich(text, ents or None)
    return Rich("")


_cache: dict = {}


async def load(session_maker) -> None:
    async with session_maker() as session:
        rows = (await session.execute(select(Setting))).scalars().all()
        _cache.clear()
        _cache.update({r.key: r.value for r in rows})


def is_set(key: str) -> bool:
    return key in _cache


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


# ---------------- тексты и кнопки ----------------

def t(key: str, **values) -> str:
    """Текст для клиента (HTML) с подстановкой {переменных}."""
    custom = (_cache.get("texts") or {}).get(key)
    spec = TEXTS.get(key)
    template = custom if custom else (spec.default if spec else key)
    if "brand" not in values:
        values["brand"] = escape(str(get("brand")))
    return fill(template, values)


def text_is_custom(key: str) -> bool:
    return bool((_cache.get("texts") or {}).get(key))


async def set_text(session: AsyncSession, key: str, html: str | None) -> None:
    texts = dict(_cache.get("texts") or {})
    if html:
        texts[key] = html
    else:
        texts.pop(key, None)
    await put(session, "texts", texts)


def button(key: str) -> dict:
    """{'text', 'icon', 'style'} кнопки с учётом правок."""
    default = BUTTONS.get(key, ("", key))[1]
    custom = (_cache.get("buttons") or {}).get(key) or {}
    return {"text": custom.get("text") or default, "icon": custom.get("icon") or "", "style": custom.get("style") or ""}


async def set_button(session: AsyncSession, key: str, **fields) -> None:
    buttons = dict(_cache.get("buttons") or {})
    current = dict(buttons.get(key) or {})
    for k, v in fields.items():
        if v:
            current[k] = v
        else:
            current.pop(k, None)
    if current:
        buttons[key] = current
    else:
        buttons.pop(key, None)
    await put(session, "buttons", buttons)


def layout(screen: str) -> list[list[str]]:
    """Раскладка кнопок экрана с учётом правок админа."""
    default = SCREENS[screen][1] if screen in SCREENS else []
    allowed = {k for row in default for k in row} | (set(MENU_KEYS) if screen == "menu" else set())
    stored = (_cache.get("layouts") or {}).get(screen)
    if screen == "menu" and stored is None:
        stored = _cache.get("menu_layout")  # старый ключ
    if not isinstance(stored, list):
        return [list(r) for r in default]
    clean, seen = [], set()
    for row in stored:
        keys = [k for k in row if k in allowed and k not in seen][:8]
        seen.update(keys)
        if keys:
            clean.append(keys)
    if screen != "menu":  # на служебных экранах кнопки не теряются, даже если раскладка старая
        for row in default:
            missing = [k for k in row if k not in seen]
            if missing:
                clean.append(missing)
                seen.update(missing)
    return clean


async def set_layout(session: AsyncSession, screen: str, rows: list[list[str]] | None) -> None:
    layouts = dict(_cache.get("layouts") or {})
    if rows is None:
        layouts.pop(screen, None)
        if screen == "menu":
            await reset(session, "menu_layout")
    else:
        layouts[screen] = [r for r in rows if r]
    await put(session, "layouts", layouts)


def menu_layout() -> list[list[str]]:
    return layout("menu")


async def set_menu_layout(session: AsyncSession, rows: list[list[str]] | None) -> None:
    await set_layout(session, "menu", rows)


# ---------------- режим редактирования ----------------

def is_editing(user_id: int) -> bool:
    return user_id in (_cache.get("edit_mode") or [])


async def set_editing(session: AsyncSession, user_id: int, on: bool) -> None:
    ids = [i for i in (_cache.get("edit_mode") or []) if i != user_id]
    if on:
        ids.append(user_id)
    await put(session, "edit_mode", ids)
