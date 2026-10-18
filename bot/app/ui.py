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
    WebAppInfo,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from .cb import Adm, Nav
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


def _with_edit_row(target, kb: InlineKeyboardMarkup | None, edit: tuple[str | None, str | None] | None):
    """В режиме редактирования админ видит под экраном кнопки правки этого экрана."""
    if not edit:
        return kb
    from .services import settings

    viewer = target.from_user.id if isinstance(target, CallbackQuery) else target.chat.id
    if not settings.is_editing(viewer):
        return kb
    text_key, screen = edit
    row = []
    if text_key:
        row.append(btn("✏️ Текст", Adm(s="live", a="tx", v=text_key)))
    if screen:
        row.append(btn("🔘 Кнопки", Adm(s="live", a="bt", v=screen)))
    if not row:
        return kb
    rows = list(kb.inline_keyboard) if kb else []
    return InlineKeyboardMarkup(inline_keyboard=rows + [row])


async def show(
    target: Message | CallbackQuery,
    content: Content,
    kb: InlineKeyboardMarkup | None = None,
    photo: str | None = None,
    edit: tuple[str | None, str | None] | None = None,
) -> Message | None:
    kb = _with_edit_row(target, kb, edit)
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


def btn(text: str, cb=None, url: str | None = None, icon: str | None = None, style: str | None = None,
        web_app: str | None = None) -> InlineKeyboardButton:
    extra = {}
    if icon:
        extra["icon_custom_emoji_id"] = icon
    if style:
        extra["style"] = style
    if web_app:
        return InlineKeyboardButton(text=text, web_app=WebAppInfo(url=web_app), **extra)
    if url:
        return InlineKeyboardButton(text=text, url=url, **extra)
    data = cb.pack() if hasattr(cb, "pack") else str(cb)
    return InlineKeyboardButton(text=text, callback_data=data, **extra)


def mbtn(key: str, cb=None, url: str | None = None, web_app: str | None = None, **values) -> InlineKeyboardButton:
    """Кнопка из реестра: текст, премиум иконка и цвет настраиваются в админке."""
    from .services import settings

    spec = settings.button(key)
    return btn(fill(spec["text"], values)[:64], cb, url=url, icon=spec["icon"] or None, style=spec["style"] or None,
               web_app=web_app)


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


def screen_kb(
    screen: str,
    buttons: dict[str, InlineKeyboardButton],
    top: list[list[InlineKeyboardButton]] | None = None,
) -> InlineKeyboardMarkup:
    """Клавиатура экрана по раскладке из админки. buttons: доступные сейчас кнопки по ключам."""
    from .services import settings

    rows = [list(r) for r in (top or []) if r]
    used = set()
    for row in settings.layout(screen):
        line = [buttons[k] for k in row if k in buttons]
        used.update(k for k in row if k in buttons)
        if line:
            rows.append(line)
    if screen != "menu":
        extra = [b for k, b in buttons.items() if k not in used]
        for b in extra:
            rows.append([b])
    return InlineKeyboardMarkup(inline_keyboard=rows)
