from urllib.parse import quote

from aiogram import F, Router
from aiogram.types import CallbackQuery
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..cb import Nav
from ..db.models import RefAccrual, User
from ..services import settings
from ..ui import back_menu, btn, kb, show
from ..utils import money, num

router = Router(name="referral")


@router.callback_query(Nav.filter(F.to == "ref"))
async def nav_ref(cb: CallbackQuery, session: AsyncSession, user: User) -> None:
    me = await cb.bot.me()
    link = f"https://t.me/{me.username}?start=r{user.id}"
    invited = await session.scalar(select(func.count(User.id)).where(User.referrer_id == user.id)) or 0
    rows = (await session.execute(
        select(RefAccrual.paid, func.coalesce(func.sum(RefAccrual.amount), 0))
        .where(RefAccrual.referrer_id == user.id).group_by(RefAccrual.paid)
    )).all()
    sums = {paid: total for paid, total in rows}
    percent = num(settings.get("ref_percent") or 0)
    base = "с прибыли" if settings.get("ref_base") == "profit" else "с суммы"
    text = (
        "👥 <b>Реферальная программа</b>\n\n"
        f"Приглашайте друзей и получайте <b>{percent}%</b> {base} каждого их заказа.\n\n"
        f"🔗 Ваша ссылка:\n<code>{link}</code>\n\n"
        f"👤 Приглашено: <b>{invited}</b>\n"
        f"💰 Начислено всего: <b>{money(sum(sums.values()) if sums else 0)}</b>\n"
        f"⏳ К выплате: <b>{money(sums.get(False, 0))}</b>\n\n"
        "Для выплаты напишите менеджеру."
    )
    share = "https://t.me/share/url?url=" + quote(link, safe="")
    await show(cb, text, kb(
        [btn("📤 Поделиться ссылкой", url=share)],
        [btn("💬 Запросить выплату", Nav(to="support"))],
        back_menu(),
    ))
