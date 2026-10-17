import re
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from html import escape

from aiogram.types import MessageEntity

from .config import config

USERNAME_RE = re.compile(r"^@?([A-Za-z][A-Za-z0-9_]{3,31})$")
_NUM_CLEAN = re.compile(r"(₸|тг|tg|kzt|тенге|ton|тон|\s)", re.IGNORECASE)


def h(value) -> str:
    """Экранирование для HTML."""
    return escape(str(value or ""), quote=False)


def parse_number(raw: str | None) -> Decimal | None:
    if not raw:
        return None
    cleaned = _NUM_CLEAN.sub("", raw.strip()).replace(",", ".")
    try:
        value = Decimal(cleaned)
    except (InvalidOperation, ValueError):
        return None
    if not value.is_finite() or value <= 0 or value > Decimal("1e12"):
        return None
    return value


def is_tenge_input(raw: str) -> bool:
    low = raw.lower()
    return any(x in low for x in ("₸", "тг", "kzt", "тенге"))


def money(value: Decimal | int | float | None, cur: str = "₸") -> str:
    if value is None:
        return "не указано"
    value = Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if value == value.to_integral_value():
        body = f"{int(value):,}".replace(",", " ")
    else:
        body = f"{value:,.2f}".replace(",", " ")
    return f"{body} {cur}".strip()


def num(value: Decimal | int | float | None) -> str:
    if value is None:
        return "не задано"
    d = Decimal(str(value)).normalize()
    if d == d.to_integral_value():
        return f"{int(d):,}".replace(",", " ")
    return format(d, "f")


def round_up(value: Decimal) -> Decimal:
    return value.quantize(Decimal("1"), rounding=ROUND_HALF_UP)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def local(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(config.tz)


def fdate(dt: datetime | None, with_time: bool = True) -> str:
    dt = local(dt)
    if dt is None:
        return "нет"
    return dt.strftime("%d.%m.%Y %H:%M" if with_time else "%d.%m.%Y")


def clean_username(raw: str | None) -> str | None:
    if not raw:
        return None
    m = USERNAME_RE.match(raw.strip())
    return m.group(1).lower() if m else None


# ---------- Текст с entities (премиум эмодзи и форматирование) ----------


@dataclass(slots=True)
class Rich:
    text: str
    entities: list[MessageEntity] | None = None


def entities_to_store(entities: list[MessageEntity] | None) -> list[dict]:
    if not entities:
        return []
    return [e.model_dump(exclude_none=True, exclude={"user"}) for e in entities if e.type != "text_mention"]


def entities_from_store(raw: list[dict] | None) -> list[MessageEntity] | None:
    if not raw:
        return None
    out = []
    for e in raw:
        try:
            out.append(MessageEntity(**e))
        except Exception:
            continue
    return out or None


def rich_store(text: str, entities: list[MessageEntity] | None) -> dict:
    return {"text": text, "entities": entities_to_store(entities)}


def rich_load(stored: dict | None, fallback: str = "") -> Rich:
    if not isinstance(stored, dict) or not stored.get("text"):
        return Rich(fallback, None)
    return Rich(stored["text"], entities_from_store(stored.get("entities")))


def strip_custom_emoji(entities: list[dict] | None) -> list[dict]:
    return [e for e in (entities or []) if e.get("type") != "custom_emoji"]


def u16(s: str) -> int:
    return len(s.encode("utf-16-le")) // 2


def fill_template(text: str, entities: list[dict] | None, values: dict[str, str]) -> tuple[str, list[dict]]:
    """Подставляет {ключи} в текст и сдвигает entities (смещения в UTF-16).

    Премиум эмодзи и форматирование вокруг плейсхолдеров сохраняются.
    """
    ents = [dict(e) for e in (entities or [])]
    matches = [m for m in re.finditer(r"\{([a-z_]+)\}", text) if m.group(1) in values]
    for m in reversed(matches):
        value = values[m.group(1)]
        start = u16(text[: m.start()])
        old_len = u16(m.group(0))
        delta = u16(value) - old_len
        end = start + old_len
        kept = []
        for e in ents:
            e_start, e_end = e["offset"], e["offset"] + e["length"]
            if e_end <= start:
                kept.append(e)
            elif e_start >= end:
                e["offset"] += delta
                kept.append(e)
            elif e_start <= start and e_end >= end:
                e["length"] += delta
                if e["length"] > 0:
                    kept.append(e)
            # частичное пересечение с плейсхолдером: entity выкидываем
        ents = kept
        text = text[: m.start()] + value + text[m.end() :]
    return text, ents
