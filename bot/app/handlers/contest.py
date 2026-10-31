"""Клиент: участие в конкурсе. Кнопка «Участвовать» — ссылка t.me/bot?start=ct<id> (работает и из канала).
Проверяем условия (подписка на каналы) и записываем в участники."""

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

CLOSED, ALREADY, MISSING, JOINED = "closed", "already", "missing", "joined"


async def _try_join(bot, session: AsyncSession, user: User, cid: int) -> tuple[str, str, object]:
    """Возвращает (итог, текст, клавиатура)."""
    c = await session.get(Contest, cid)
    if c is None or c.status != "active" or c.ends_at <= utcnow():
        return CLOSED, "Этот конкурс уже завершён.", None
    when, channels = svc.deadline_text(c), c.channels
    exists = await session.scalar(select(ContestEntry.id).where(
        ContestEntry.contest_id == cid, ContestEntry.user_id == user.id))
    if exists:
        return ALREADY, f"Вы уже участвуете. Итоги: {when} (время Алматы). Удачи! 🍀", None
    missing = await svc.missing_subs(bot, channels, user.id)
    if missing:
        text = "Чтобы участвовать, подпишитесь:\n\n" + "\n".join(
            f"• {ch.get('title') or ch['chat']}" for ch in missing) + "\n\nЗатем нажмите «✅ Проверить»."
        return MISSING, text, svc.conditions_kb(cid, missing)
    session.add(ContestEntry(contest_id=cid, user_id=user.id))
    try:
        await session.commit()
    except IntegrityError:  # двойное нажатие
        await session.rollback()
        return ALREADY, f"Вы уже участвуете. Итоги: {when} (время Алматы). Удачи! 🍀", None
    return JOINED, f"✅ Вы участвуете! Итоги: {when} (время Алматы). Удачи! 🍀", None


async def open_contest(message: Message, session: AsyncSession, user: User, cid: int) -> None:
    """Нажатие «Участвовать» (ссылка t.me/bot?start=ct<id>) в личке или в канале."""
    _, text, markup = await _try_join(message.bot, session, user, cid)
    await message.answer(text, reply_markup=markup)


@router.callback_query(Cn.filter(F.a.in_({"join", "check"})))
async def on_button(cb: CallbackQuery, callback_data: Cn, session: AsyncSession, user: User) -> None:
    """«✅ Проверить» под условиями (и старые кнопки «Участвовать», разосланные раньше)."""
    status, text, markup = await _try_join(cb.bot, session, user, callback_data.i)
    if status == MISSING and callback_data.a == "check":
        await answer(cb, "Подписка ещё не на все каналы", alert=True)
    else:
        await answer(cb)
    if callback_data.a == "check":
        with suppress(TelegramBadRequest):
            await cb.message.edit_text(text, reply_markup=markup)
    else:
        await cb.message.answer(text, reply_markup=markup)
