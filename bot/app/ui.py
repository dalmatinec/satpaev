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
from .utils import Rich

log = logging.getLogger(__name__)

Content = str | Rich


def _text_kwargs(content: Content) -> dict:
    if isinstance(content, Rich):
        return {"text": content.text or "...", "entities": content.entities, "parse_mode": None}
    return {"text": content}


def _caption_kwargs(content: Content) -> dict:
    if isinstance(content, Rich):
        return {"caption": content.text[:1024], "caption_entities": content.entities, "parse_mode": None}
    return {"caption": content}


async def answer(cb: CallbackQuery, text: str | None = None, alert: bool = False) -> None:
    with suppress(TelegramBadRequest):
        await cb.answer(text, show_alert=alert)


async def show(
    target: Message | CallbackQuery,
    content: Content,
    kb: InlineKeyboardMarkup | None = None,
    photo: str | None = None,
) -> Message | None:
    """Показать экран: отредактировать текущее сообщение или прислать новое."""
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
                log.debug("edit failed: %s", e)
            with suppress(TelegramBadRequest):
                await msg.delete()
    else:
        chat_id = target.chat.id
    try:
        if photo:
            try:
                return await bot.send_photo(chat_id, photo, **_caption_kwargs(content), reply_markup=kb)
            except TelegramBadRequest:
                pass  # файл недоступен, показываем текстом
        return await bot.send_message(chat_id, **_text_kwargs(content), reply_markup=kb)
    except TelegramBadRequest as e:
        if isinstance(content, Rich) and content.entities:
            # если премиум эмодзи недоступны (кончился Premium), шлём без них
            safe = Rich(content.text, [x for x in content.entities if x.type != "custom_emoji"] or None)
            return await bot.send_message(chat_id, **_text_kwargs(safe), reply_markup=kb)
        raise e


async def send_safe(bot: Bot, chat_id: int, content: Content, kb: InlineKeyboardMarkup | None = None) -> Message | None:
    """Отправка уведомления без падений (клиент мог заблокировать бота)."""
    try:
        return await bot.send_message(chat_id, **_text_kwargs(content), reply_markup=kb)
    except TelegramRetryAfter as e:
        await asyncio.sleep(e.retry_after + 1)
        with suppress(TelegramBadRequest, TelegramForbiddenError):
            return await bot.send_message(chat_id, **_text_kwargs(content), reply_markup=kb)
    except (TelegramBadRequest, TelegramForbiddenError) as e:
        log.info("send to %s failed: %s", chat_id, e)
    return None


def kb(*rows: list[InlineKeyboardButton]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[list(r) for r in rows if r])


def btn(text: str, cb=None, url: str | None = None) -> InlineKeyboardButton:
    if url:
        return InlineKeyboardButton(text=text, url=url)
    data = cb.pack() if hasattr(cb, "pack") else str(cb)
    return InlineKeyboardButton(text=text, callback_data=data)


def back_menu() -> list[InlineKeyboardButton]:
    return [btn("🏠 Главное меню", Nav(to="menu"))]


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
