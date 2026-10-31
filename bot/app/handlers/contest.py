"""Клиент: участие в конкурсе кнопкой «Участвовать» под постом."""

from aiogram import F, Router
from aiogram.types import CallbackQuery
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..cb import Cn
from ..db.models import Contest, ContestEntry, User
from ..services.contest import deadline_text
from ..ui import answer
from ..utils import utcnow

router = Router(name="contest")


@router.callback_query(Cn.filter(F.a == "join"))
async def join(cb: CallbackQuery, callback_data: Cn, session: AsyncSession, user: User) -> None:
    c = await session.get(Contest, callback_data.i)
    if c is None or c.status != "active" or c.ends_at <= utcnow():
        await answer(cb, "Конкурс уже завершён", alert=True)
        return
    when = deadline_text(c)
    exists = await session.scalar(select(ContestEntry.id).where(
        ContestEntry.contest_id == c.id, ContestEntry.user_id == user.id))
    if exists:
        await answer(cb, "Вы уже участвуете. Удачи! 🍀")
        return
    session.add(ContestEntry(contest_id=c.id, user_id=user.id))
    try:
        await session.commit()
    except IntegrityError:  # повторный двойной клик
        await session.rollback()
        await answer(cb, "Вы уже участвуете. Удачи! 🍀")
        return
    await answer(cb, f"✅ Вы участвуете! Итоги: {when}")
