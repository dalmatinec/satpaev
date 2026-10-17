from urllib.parse import quote

from aiogram import F, Router
from aiogram.types import CallbackQuery
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..cb import Nav
from ..db.models import RefAccrual, User
from ..services import media, settings
from ..ui import back_menu, kb, mbtn, show
from ..utils import money, num

router = Router(name="referral")


async def ref_view(target, session: AsyncSession, user: User) -> None:
    me = await target.bot.me()
    link = f"https://t.me/{me.username}?start=r{user.id}"
    invited = await session.scalar(select(func.count(User.id)).where(User.referrer_id == user.id)) or 0
    rows = (await session.execute(
        select(RefAccrual.paid, func.coalesce(func.sum(RefAccrual.amount), 0))
        .where(RefAccrual.referrer_id == user.id).group_by(RefAccrual.paid)
    )).all()
    sums = {paid: total for paid, total in rows}
    text = settings.t(
        "ref_screen",
        percent=num(settings.get("ref_percent") or 0),
        base="с прибыли" if settings.get("ref_base") == "profit" else "с суммы",
        link=link,
        invited=invited,
        total=money(sum(sums.values()) if sums else 0),
        pending=money(sums.get(False, 0)),
    )
    share = "https://t.me/share/url?url=" + quote(link, safe="")
    await show(target, text, kb(
        [mbtn("ref_share", url=share)],
        [mbtn("ref_payout", Nav(to="support"))],
        back_menu(),
    ), photo=media.photo("ref"))


@router.callback_query(Nav.filter(F.to == "ref"))
async def nav_ref(cb: CallbackQuery, session: AsyncSession, user: User) -> None:
    await ref_view(cb, session, user)
