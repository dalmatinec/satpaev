"""Публикация в канал: через аккаунт (постер Telethon, с премиум эмодзи) или через бота."""

import logging
import os
import uuid
from datetime import datetime

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import MessageEntity
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import config
from ..db.models import Post, PosterStatus, Rate
from ..utils import fill_template, money, num, strip_custom_emoji, utcnow
from . import settings

log = logging.getLogger(__name__)

POSTER_STATES = {
    "online": "🟢 На связи",
    "unauthorized": "🔑 Нужен вход в аккаунт",
    "disabled": "⚪ Не настроен (нет API ID/HASH)",
    "error": "🔴 Ошибка, переподключается",
    "flood": "🟡 Пауза по лимиту Telegram",
    "starting": "🟡 Запускается",
}


async def poster_status(session: AsyncSession) -> tuple[bool, str, str]:
    row = await session.get(PosterStatus, 1)
    if row is None:
        return False, "Постер ещё не запускался", ""
    updated = row.updated_at
    if updated.tzinfo is None:
        updated = updated.replace(tzinfo=utcnow().tzinfo)
    age = (utcnow() - updated).total_seconds()
    state = POSTER_STATES.get(row.state, row.state)
    if age > 180:
        return False, f"🔴 Не отвечает {int(age // 60)} мин", row.info
    return row.state == "online", state, row.info


def _entities(raw: list[dict] | None) -> list[MessageEntity] | None:
    out = []
    for e in raw or []:
        try:
            out.append(MessageEntity(**e))
        except Exception:
            continue
    return out or None


async def publish(
    session: AsyncSession,
    bot: Bot,
    text: str,
    entities: list[dict] | None,
    photo_file_id: str | None = None,
    kind: str = "news",
    target: str | None = None,
) -> tuple[bool, str]:
    """Возвращает (успех, описание)."""
    target = target or config.channel_id
    if not target:
        return False, "Не указан канал (CHANNEL_ID в .env)"
    mode = settings.get("post_mode") or "bot"
    if mode == "account" and config.poster_enabled:
        media = ""
        if photo_file_id:
            os.makedirs(os.path.join(config.shared_dir, "media"), exist_ok=True)
            media = os.path.join(config.shared_dir, "media", f"{uuid.uuid4().hex}.jpg")
            await bot.download(photo_file_id, destination=media)
        post = Post(kind=kind, mode="account", target=target, text=text, entities=entities or [], media=media)
        session.add(post)
        await session.commit()
        return True, f"Пост #{post.id} в очереди, аккаунт опубликует в течение минуты"

    post = Post(kind=kind, mode="bot", target=target, text=text, entities=entities or [], status="sending")
    session.add(post)
    await session.flush()
    ok, info = await _send_by_bot(bot, target, text, entities, photo_file_id)
    post.status = "sent" if ok else "failed"
    post.error = "" if ok else info
    post.sent_at = utcnow() if ok else None
    await session.commit()
    return ok, info


async def _send_by_bot(bot: Bot, target: str, text: str, entities, photo) -> tuple[bool, str]:
    attempts = [entities or [], strip_custom_emoji(entities)]
    last_error = ""
    for ents in attempts:
        try:
            if photo:
                await bot.send_photo(target, photo, caption=text[:1024], caption_entities=_entities(ents), parse_mode=None)
            else:
                await bot.send_message(target, text, entities=_entities(ents), parse_mode=None)
            note = "" if ents == (entities or []) else " (премиум эмодзи боту в канал недоступны, отправлено без них)"
            return True, "Опубликовано ботом" + note
        except TelegramForbiddenError:
            return False, "Бот не админ канала"
        except TelegramBadRequest as e:
            last_error = str(e)
            log.warning("post by bot failed: %s", e)
    return False, f"Ошибка: {last_error}"


async def rates_post(session: AsyncSession, bot: Bot) -> tuple[str, list[dict]]:
    rates = (await session.execute(
        select(Rate).where(Rate.is_active.is_(True)).order_by(Rate.sort, Rate.id)
    )).scalars().all()
    lines = []
    for r in rates:
        parts = []
        if r.buy:
            parts.append(f"покупаем {num(r.buy)} ₸")
        if r.sell:
            parts.append(f"продаём {num(r.sell)} ₸")
        lines.append(f"• {r.code}: " + " · ".join(parts))
    tiers = settings.star_tiers()
    stars_min = f"{num(min(p for _, p in tiers))} ₸ за шт" if tiers else "по запросу"
    me = await bot.me()
    template, ents = settings.rich_raw("rates_template")
    values = {
        "date": datetime.now(config.tz).strftime("%d.%m.%Y"),
        "rates": "\n".join(lines) or "по запросу",
        "stars_min": stars_min,
        "sla_exchange": str(settings.get("sla_exchange")),
        "sla_stars": str(settings.get("sla_stars")),
        "bot": f"@{me.username}",
        "brand": str(settings.get("brand")),
        "ton": money(settings.get("ton_kzt")) if settings.get("ton_kzt") else "по запросу",
    }
    return fill_template(template, ents, values)
