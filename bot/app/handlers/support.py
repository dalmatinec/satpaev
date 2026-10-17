"""Связь через бота: клиент пишет боту, менеджер отвечает реплаем. Личный аккаунт не светится."""

import logging
import time
from contextlib import suppress

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, ReactionTypeEmoji, ReplyParameters
from sqlalchemy.ext.asyncio import AsyncSession

from ..cb import Adm, Nav
from ..config import config
from ..db.models import SupportLink, User
from ..services import media, settings, workhours
from ..services.orders import tag_name
from ..states import SupportSt
from ..ui import btn, kb, mbtn, show
from ..utils import h

log = logging.getLogger(__name__)
router = Router(name="support")

_last_header: dict[int, tuple[float, dict[int, int]]] = {}
_last_after_hours: dict[int, float] = {}


async def support_view(target, state: FSMContext) -> None:
    await state.set_state(SupportSt.chat)
    await show(target, settings.t("support_screen"), kb([mbtn("finish_chat", Nav(to="menu"))]),
               photo=media.photo("support"))


@router.callback_query(Nav.filter(F.to == "support"))
async def nav_support(cb: CallbackQuery, state: FSMContext) -> None:
    await support_view(cb, state)


async def _react(message: Message) -> None:
    with suppress(TelegramBadRequest, TelegramForbiddenError):
        await message.react([ReactionTypeEmoji(emoji="👍")])


async def forward_to_admins(message: Message, user: User, session: AsyncSession) -> None:
    bot = message.bot
    now = time.monotonic()
    prev = _last_header.get(user.id)
    headers = prev[1] if prev and now - prev[0] < 120 else {}
    if len(_last_header) > 5000:
        _last_header.clear()
    for admin_id in config.admin_ids:
        try:
            header_id = headers.get(admin_id)
            if not header_id:
                header = await bot.send_message(
                    admin_id,
                    f"💬 <b>Сообщение от клиента</b>\n{h(user.full_name)} ({h(user.mention)}) · <code>{user.id}</code>"
                    + (f" · {tag_name(user.tag)}" if user.tag else "")
                    + "\n\n<i>Ответьте реплаем на сообщение ниже или кнопкой.</i>",
                    reply_markup=kb([
                        btn("💬 Ответить", Adm(s="cl", a="write", i=user.id)),
                        btn("👤 Клиент", Adm(s="cl", a="card", i=user.id)),
                    ]),
                )
                header_id = header.message_id
                headers[admin_id] = header_id
                session.add(SupportLink(admin_chat_id=admin_id, admin_msg_id=header_id, user_id=user.id))
            copied = await bot.copy_message(
                admin_id, message.chat.id, message.message_id,
                reply_parameters=ReplyParameters(message_id=header_id, allow_sending_without_reply=True),
            )
            session.add(SupportLink(admin_chat_id=admin_id, admin_msg_id=copied.message_id, user_id=user.id))
        except (TelegramBadRequest, TelegramForbiddenError) as e:
            log.warning("support forward to %s failed: %s", admin_id, e)
    _last_header[user.id] = (now, headers)
    await session.commit()
    await _react(message)
    if not workhours.is_working():
        last = _last_after_hours.get(user.id, 0.0)
        if now - last > 3 * 3600:
            _last_after_hours[user.id] = now
            await show(message, settings.t("after_hours", time=h(settings.get("work_from"))))


async def deliver_to_user(bot: Bot, admin_message: Message, user_id: int) -> tuple[bool, str]:
    try:
        await bot.copy_message(user_id, admin_message.chat.id, admin_message.message_id)
        return True, ""
    except TelegramForbiddenError:
        return False, "Клиент заблокировал бота"
    except TelegramBadRequest as e:
        return False, str(e)


@router.message(SupportSt.chat)
async def support_message(message: Message, user: User, session: AsyncSession, is_admin: bool) -> None:
    if is_admin:
        await message.answer("Вы админ: сообщения клиентов приходят вам сюда. Чтобы ответить, используйте реплай.")
        return
    await forward_to_admins(message, user, session)


@router.message(F.chat.type == "private")
async def fallback(message: Message, user: User, session: AsyncSession, is_admin: bool) -> None:
    """Любое сообщение вне сценариев уходит менеджеру."""
    if is_admin:
        await message.answer("ℹ️ Чтобы ответить клиенту, сделайте реплай на его сообщение.\nАдминка: /start → ⚙️ Админка")
        return
    if message.text and message.text.startswith("/"):
        await message.answer(settings.t("unknown_cmd"))
        return
    await forward_to_admins(message, user, session)
