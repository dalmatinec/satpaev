"""Публикация в канал: через аккаунт (постер Telethon, с премиум эмодзи) или через бота."""

import asyncio
import logging
import os
import shutil
import uuid
from datetime import datetime, timedelta

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from aiogram.types import MessageEntity
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import config
from ..db.models import BotChat, Post, PosterStatus, Rate, Setting
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
            parts.append(f"покупаем {num(r.buy).replace('.', ',')} ₸")
        if r.sell:
            parts.append(f"продаём {num(r.sell).replace('.', ',')} ₸")
        lines.append(f"🔹 {r.code}: " + " · ".join(parts))
    tiers = settings.star_tiers()
    stars_min = f"{num(min(p for _, p in tiers))} ₸ за шт" if tiers else "по запросу"
    me = await bot.me()
    template, ents = settings.rich_raw("rates_template")
    if template.strip().startswith("/"):  # в шаблон случайно попала команда (например /start): берём стандартный
        template, ents = settings.default_rich_raw("rates_template")
    now = datetime.now(config.tz)
    try:
        hours = max(0.5, float(settings.get("rates_valid_hours") or 3))
    except (TypeError, ValueError):
        hours = 3.0
    start = now.replace(minute=0, second=0, microsecond=0)  # «с 09:00», даже если опубликовали в 09:46
    until = start + timedelta(hours=hours)
    h_ = now.hour
    greeting = ("☀️ Всем доброе утро!" if 5 <= h_ < 12 else "🌤 Всем добрый день!" if 12 <= h_ < 17
                else "🌆 Всем добрый вечер!" if 17 <= h_ < 23 else "🌙 Всем доброй ночи!")
    values = {
        "date": now.strftime("%d.%m.%Y"),
        "time": now.strftime("%H:%M"),
        "valid": f"с {start.strftime('%H:%M')} до {until.strftime('%H:%M')}",
        "greeting": greeting,
        "rates": "\n".join(lines) or "по запросу",
        "stars_min": stars_min,
        "sla_exchange": str(settings.get("sla_exchange")),
        "sla_stars": str(settings.get("sla_stars")),
        "bot": f"@{me.username}",
        "brand": str(settings.get("brand")),
        "ton": money(settings.get("ton_kzt")) if settings.get("ton_kzt") else "по запросу",
        "fee": (f"{settings.get('ex_fee_name') or 'Сервисный сбор'}: {money(settings.get('ex_fee'))} за сделку"
                if settings.get("ex_fee") else "без сбора"),
    }
    return fill_template(template, ents, values)


# ---------------- посты товаров: подарок, юзер, звёзды, Premium ----------------

def _render(*parts) -> tuple[str, list[dict]]:
    from aiogram.utils.formatting import Text

    text, ents = Text(*parts).render()
    return text, [e.model_dump(exclude_none=True) for e in (ents or [])]


async def _deep(bot: Bot, start: str) -> str:
    me = await bot.me()
    return f"https://t.me/{me.username}?start={start}"


def _kzt(value) -> str:
    return money(value).replace(".", ",")


async def item_post(bot: Bot, item) -> tuple[str, list[dict]]:
    """Пост о подарке или готовом юзернейме. Ссылка ведёт прямо на карточку в боте."""
    from aiogram.utils.formatting import Bold, TextLink

    if item.kind == "uname":
        from ..handlers.admin.catalog import ready_price

        price_ton, price_kzt = ready_price(item)
        price = f"{price_ton} TON" + (f" (≈ {_kzt(price_kzt)})" if price_kzt else "")
        head, label, start = ["💎 Юзернейм ", Bold(f"@{item.title}")], "🛒 Купить в боте", "un"
        sla = str(settings.get("sla_gifts") or "")
    else:
        price = _kzt(item.price) if item.price else (item.price_text or "по запросу")
        head, label, start = ["🎁 ", Bold(item.title)], "🛒 Купить в боте", f"gift_{item.id}"
        sla = str(settings.get("sla_gifts") or "")
    parts = [*head, "\n"]
    if item.description:
        parts += ["\n", item.description[:600], "\n"]
    parts += ["\n💰 Цена: ", Bold(price), "\n"]
    if sla:
        parts += ["⏱ Передача: ", sla, "\n"]
    parts += ["\n", TextLink(label, url=await _deep(bot, start))]
    return _render(*parts)


async def stars_post(bot: Bot) -> tuple[str, list[dict]]:
    from aiogram.utils.formatting import Bold, TextLink

    lines = []
    for q, p in settings.star_tiers():
        lines.append(f"🔹 от {num(q)} шт: {num(p).replace('.', ',')} ₸ за звезду\n")
    return _render(
        "⭐ ", Bold("Telegram Stars"), "\n\n", "Чем больше берёте, тем дешевле звезда:\n", *lines, "\n",
        "⏱ Выдача: ", str(settings.get("sla_stars") or ""), "\n",
        "📦 Минимальный заказ: ", Bold(_kzt(settings.min_order())), "\n\n",
        TextLink("🛒 Купить звёзды в боте", url=await _deep(bot, "stars")),
    )


async def premium_post(bot: Bot, session: AsyncSession) -> tuple[str, list[dict]]:
    from aiogram.utils.formatting import Bold, TextLink

    from ..handlers import premium

    await premium.refresh_rate(session)
    lines = []
    for m, usd in premium.plans():
        kzt = premium.price_kzt(usd)
        lines.append(f"🔹 {premium.period(m)}: {num(usd)} $" + (f" · {_kzt(kzt)}" if kzt else "") + "\n")
    return _render(
        "👑 ", Bold("Telegram Premium"), "\n\n", "Подключим вам или в подарок другу. Вход в аккаунт не нужен, только юзернейм.\n\n",
        *lines, "\n", "⏱ Подключение: ", str(settings.get("sla_premium") or ""), "\n\n",
        TextLink("👑 Подключить в боте", url=await _deep(bot, "premium")),
    )


# ---------------- мультипостинг ----------------

MEDIA_EXT = {"photo": ".jpg", "video": ".mp4", "animation": ".mp4", "document": ""}


def media_of(message) -> tuple[str | None, str, str]:
    """(file_id, вид, имя файла) медиа из сообщения, которое умеет отправить аккаунт."""
    if message.photo:
        return message.photo[-1].file_id, "photo", ""
    if message.animation:
        return message.animation.file_id, "animation", message.animation.file_name or ""
    if message.video:
        return message.video.file_id, "video", message.video.file_name or ""
    if message.document:
        return message.document.file_id, "document", message.document.file_name or ""
    return None, "", ""


async def download_media(bot: Bot, file_id: str, kind: str, name: str = "") -> str:
    folder = os.path.join(config.shared_dir, "media")
    os.makedirs(folder, exist_ok=True)
    ext = MEDIA_EXT.get(kind, "") or os.path.splitext(name)[1][:10]
    path = os.path.join(folder, f"{uuid.uuid4().hex}{ext}")
    await bot.download(file_id, destination=path)
    return path


def clone_media(path: str) -> str:
    """Своя копия файла на каждый пост: очистка удаляет файл после отправки."""
    if not path:
        return ""
    new = os.path.join(os.path.dirname(path), f"{uuid.uuid4().hex}{os.path.splitext(path)[1]}")
    shutil.copyfile(path, new)
    return new


async def queue_account(session: AsyncSession, target: str, text: str, entities, media: str = "",
                        media_kind: str = "", kind: str = "news") -> Post:
    post = Post(kind=kind, mode="account", target=str(target), text=text, entities=entities or [],
                media=media, media_kind=media_kind)
    session.add(post)
    await session.flush()
    return post


async def copy_by_bot(bot: Bot, target: str, from_chat: int, msg_id: int, text: str, entities, photo: str | None) -> tuple[bool, str]:
    """Копия сообщения без пометки «переслано». Если Telegram не принял премиум эмодзи, шлём без них."""
    try:
        await bot.copy_message(target, from_chat, msg_id)
        return True, "Опубликовано ботом"
    except TelegramForbiddenError:
        return False, "Бот не админ канала"
    except TelegramBadRequest as e:
        log.info("copy to %s failed: %s", target, e)
    return await _send_by_bot(bot, target, text, entities, photo)


async def request_refresh(session: AsyncSession) -> None:
    """Попросить постер обновить список каналов аккаунта."""
    await session.merge(Setting(key="poster_refresh", value=utcnow().isoformat()))
    await session.commit()


async def run_chats(bot: Bot, sm, from_chat: int, msg_id: int, admin_id: int) -> None:
    """Копирует пост во все группы, где есть бот. Без пересылки, с сохранением оформления."""
    sent = failed = 0
    async with sm() as session:
        chats = (await session.execute(
            select(BotChat.id).where(BotChat.active.is_(True), BotChat.type.in_(("group", "supergroup")))
        )).scalars().all()
    gone = []
    for chat_id in chats:
        try:
            await bot.copy_message(chat_id, from_chat, msg_id)
            sent += 1
        except TelegramRetryAfter as e:
            await asyncio.sleep(e.retry_after + 1)
            try:
                await bot.copy_message(chat_id, from_chat, msg_id)
                sent += 1
            except Exception:
                failed += 1
        except TelegramForbiddenError:
            failed += 1
            gone.append(chat_id)
        except TelegramBadRequest as e:
            failed += 1
            if "not found" in str(e).lower() or "kicked" in str(e).lower():
                gone.append(chat_id)
        await asyncio.sleep(0.1)
    if gone:
        async with sm() as session:
            await session.execute(update(BotChat).where(BotChat.id.in_(gone)).values(active=False))
            await session.commit()
    try:
        await bot.send_message(admin_id, f"💬 Пост в чаты: доставлено <b>{sent}</b>, ошибок <b>{failed}</b>")
    except (TelegramBadRequest, TelegramForbiddenError):
        pass
