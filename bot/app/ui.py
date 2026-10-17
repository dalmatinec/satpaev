"""Экраны: бот редактирует одно сообщение вместо того, чтобы засорять чат."""

import asyncio
import logging
from contextlib import suppress

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto,
    Message,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from .cb import Nav
from .texts import fill
from .utils import Rich

log = logging.getLogger(__name__)

Content = str | Rich
CAPTION_LIMIT = 1024


def _text_kwargs(content: Content) -> dict:
    if isinstance(content, Rich):
        return {"text": content.text or "...", "entities": content.entities, "parse_mode": None}
    return {"text": content}


def _caption_kwargs(content: Content) -> dict:
    if isinstance(content, Rich):
        return {"caption": content.text[:CAPTION_LIMIT], "caption_entities": content.entities, "parse_mode": None}
    return {"caption": content}


def _too_long_for_caption(content: Content) -> bool:
    text = content.text if isinstance(content, Rich) else content
    return len(text) > CAPTION_LIMIT


def plain_kb(markup: InlineKeyboardMarkup | None) -> InlineKeyboardMarkup | None:
    """Та же клавиатура без премиум иконок и цветов (если Telegram их не принял)."""
    if markup is None:
        return None
    rows = [[b.model_copy(update={"icon_custom_emoji_id": None, "style": None}) for b in row]
            for row in markup.inline_keyboard]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _has_extras(markup: InlineKeyboardMarkup | None) -> bool:
    return bool(markup and any(b.icon_custom_emoji_id or b.style for row in markup.inline_keyboard for b in row))


async def answer(cb: CallbackQuery, text: str | None = None, alert: bool = False) -> None:
    with suppress(TelegramBadRequest):
        await cb.answer(text[:200] if text else text, show_alert=alert)


async def show(
    target: Message | CallbackQuery,
    content: Content,
    kb: InlineKeyboardMarkup | None = None,
    photo: str | None = None,
) -> Message | None:
    try:
        return await _show(target, content, kb, photo)
    except TelegramBadRequest as e:
        if _has_extras(kb):
            log.info("клавиатура с иконками не принята (%s), показываю без них", e)
            return await _show(target, content, plain_kb(kb), photo)
        raise


async def _show(target, content: Content, kb, photo: str | None) -> Message | None:
    """Показать экран: отредактировать текущее сообщение или прислать новое."""
    if photo and _too_long_for_caption(content):
        photo = None  # подпись к фото ограничена 1024 символами
    bot: Bot = target.bot
    if isinstance(target, CallbackQuery):
        await answer(target)
        msg = target.message
        chat_id = target.from_user.id
        if isinstance(msg, Message):
            try:
                if photo and msg.photo:
                    await msg.edit_media(InputMediaPhoto(media=photo, **_caption_kwargs(content)), reply_markup=kb)
                    return msg
                if not photo and msg.text is not None:
                    await msg.edit_text(**_text_kwargs(content), reply_markup=kb)
                    return msg
            except TelegramBadRequest as e:
                if "not modified" in str(e):
                    return msg
                if _has_extras(kb):
                    raise
                log.debug("edit failed: %s", e)
            with suppress(TelegramBadRequest):
                await msg.delete()
    else:
        chat_id = target.chat.id
    if photo:
        try:
            return await bot.send_photo(chat_id, photo, **_caption_kwargs(content), reply_markup=kb)
        except TelegramBadRequest as e:
            if _has_extras(kb):
                raise
            log.info("photo failed, sending text: %s", e)
    try:
        return await bot.send_message(chat_id, **_text_kwargs(content), reply_markup=kb)
    except TelegramBadRequest:
        if isinstance(content, Rich) and content.entities:
            safe = Rich(content.text, [x for x in content.entities if x.type != "custom_emoji"] or None)
            return await bot.send_message(chat_id, **_text_kwargs(safe), reply_markup=kb)
        raise


async def send_safe(bot: Bot, chat_id: int, content: Content, kb: InlineKeyboardMarkup | None = None) -> Message | None:
    """Отправка уведомления без падений (клиент мог заблокировать бота)."""
    for attempt in range(3):
        try:
            return await bot.send_message(chat_id, **_text_kwargs(content), reply_markup=kb)
        except TelegramRetryAfter as e:
            await asyncio.sleep(e.retry_after + 1)
        except TelegramBadRequest as e:
            if _has_extras(kb):
                kb = plain_kb(kb)
                continue
            log.info("send to %s failed: %s", chat_id, e)
            return None
        except TelegramForbiddenError as e:
            log.info("send to %s failed: %s", chat_id, e)
            return None
    return None


def kb(*rows: list[InlineKeyboardButton]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[list(r) for r in rows if r])


def btn(text: str, cb=None, url: str | None = None, icon: str | None = None, style: str | None = None) -> InlineKeyboardButton:
    extra = {}
    if icon:
        extra["icon_custom_emoji_id"] = icon
    if style:
        extra["style"] = style
    if url:
        return InlineKeyboardButton(text=text, url=url, **extra)
    data = cb.pack() if hasattr(cb, "pack") else str(cb)
    return InlineKeyboardButton(text=text, callback_data=data, **extra)


def mbtn(key: str, cb=None, url: str | None = None, **values) -> InlineKeyboardButton:
    """Кнопка из реестра: текст, премиум иконка и цвет настраиваются в админке."""
    from .services import settings

    spec = settings.button(key)
    return btn(fill(spec["text"], values)[:64], cb, url=url, icon=spec["icon"] or None, style=spec["style"] or None)


def back_menu() -> list[InlineKeyboardButton]:
    return [mbtn("home", Nav(to="menu"))]


def pager(builder: InlineKeyboardBuilder, page: int, total_pages: int, make_cb) -> None:
    if total_pages <= 1:
        return
    row = []
    if page > 0:
        row.append(btn("◀️", make_cb(page - 1)))
    row.append(btn(f"{page + 1}/{total_pages}", make_cb(page)))
    if page < total_pages - 1:
        row.append(btn("▶️", make_cb(page + 1)))
    builder.row(*row)
