"""Клиент: участие в конкурсе. Проверка условий (подписка на каналы) и запись в участники."""

from contextlib import suppress

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..cb import Cn
from ..db.models import Contest, ContestEntry, User
from ..services import contest as svc
from ..ui import answer
from ..utils import utcnow

router = Router(name="contest")


def _is_open(c: Contest | None) -> bool:
    return c is not None and c.status == "active" and c.ends_at > utcnow()


async def open_contest(message: Message, session: AsyncSession, cid: int) -> None:
    """Ссылка t.me/bot?start=ct<id> из поста в канале: показываем конкурс с кнопкой участия."""
    c = await session.get(Contest, cid)
    if not _is_open(c):
        await message.answer("Этот конкурс уже завершён.")
        return
    await svc._send(message.bot, message.chat.id, svc.body(c), svc.join_kb(cid))


@router.callback_query(Cn.filter(F.a.in_({"join", "check"})))
async def join(cb: CallbackQuery, callback_data: Cn, session: AsyncSession, user: User) -> None:
    checking = callback_data.a == "check"
    c = await session.get(Contest, callback_data.i)
    if not _is_open(c):
        await answer(cb, "Конкурс уже завершён", alert=True)
        return
    cid, when, channels = c.id, svc.deadline_text(c), c.channels
    exists = await session.scalar(select(ContestEntry.id).where(
        ContestEntry.contest_id == cid, ContestEntry.user_id == user.id))
    if exists:
        await answer(cb, "Вы уже участвуете. Удачи! 🍀")
        return
    missing = await svc.missing_subs(cb.bot, channels, user.id)
    if missing:
        text = "Чтобы участвовать, подпишитесь:\n\n" + "\n".join(
            f"• {ch.get('title') or ch['chat']}" for ch in missing) + "\n\nЗатем нажмите «✅ Проверить»."
        if checking:
            await answer(cb, "Подписка ещё не на все каналы", alert=True)
            with suppress(TelegramBadRequest):
                await cb.message.edit_text(text, reply_markup=svc.conditions_kb(cid, missing))
        else:
            await answer(cb)
            await cb.message.answer(text, reply_markup=svc.conditions_kb(cid, missing))
        return
    session.add(ContestEntry(contest_id=cid, user_id=user.id))
    try:
        await session.commit()
    except IntegrityError:  # двойной клик
        await session.rollback()
        await answer(cb, "Вы уже участвуете. Удачи! 🍀")
        return
    done = f"✅ Вы участвуете! Итоги: {when}"
    if checking:
        await answer(cb, done)
        with suppress(TelegramBadRequest):
            await cb.message.edit_text(done + " (время Алматы). Удачи! 🍀")
    else:
        await answer(cb, done, alert=True)
