from datetime import datetime, time, timedelta, timezone

from aiogram import F, Router
from aiogram.types import CallbackQuery
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...cb import Adm
from ...config import config
from ...db.models import Order, Review, User
from ...services.orders import ACTIVE, kind_name
from ...ui import btn, kb, show
from ...utils import money
from .common import screen

router = Router(name="admin_stats")

PERIODS = {"today": "Сегодня", "yesterday": "Вчера", "7": "7 дней", "30": "30 дней", "all": "Всё время"}


def _range(period: str) -> tuple[datetime | None, datetime | None]:
    now = datetime.now(config.tz)
    start_today = datetime.combine(now.date(), time(0), tzinfo=config.tz)
    if period == "today":
        return start_today.astimezone(timezone.utc), None
    if period == "yesterday":
        return (start_today - timedelta(days=1)).astimezone(timezone.utc), start_today.astimezone(timezone.utc)
    if period in ("7", "30"):
        return (start_today - timedelta(days=int(period) - 1)).astimezone(timezone.utc), None
    return None, None


@screen("stat")
async def view(target, session: AsyncSession, cbd: Adm) -> None:
    period = cbd.v if cbd.v in PERIODS else "today"
    start, end = _range(period)
    cond = [Order.status == "done"]
    if start:
        cond.append(Order.done_at >= start)
    if end:
        cond.append(Order.done_at < end)
    rows = (await session.execute(
        select(
            Order.kind,
            func.count(Order.id),
            func.coalesce(func.sum(Order.amount), 0),
            func.coalesce(func.sum(Order.amount - Order.cost), 0),
            func.count(Order.cost),
        ).where(*cond).group_by(Order.kind)
    )).all()
    users_cond = []
    if start:
        users_cond.append(User.created_at >= start)
    if end:
        users_cond.append(User.created_at < end)
    new_users = await session.scalar(select(func.count(User.id)).where(*users_cond)) or 0
    active = await session.scalar(select(func.count(Order.id)).where(Order.status.in_(ACTIVE))) or 0
    rating = (await session.execute(select(func.count(Review.id), func.avg(Review.rating)))).one()

    total_cnt = sum(r[1] for r in rows)
    total_amount = sum(r[2] for r in rows)
    total_profit = sum(r[3] for r in rows)
    lines = [
        f"📊 <b>Статистика · {PERIODS[period]}</b>\n",
        f"✅ Выполнено заказов: <b>{total_cnt}</b>",
        f"💳 Оборот: <b>{money(total_amount)}</b>",
        f"💰 Прибыль: <b>{money(total_profit)}</b>",
        f"🆕 Новых клиентов: <b>{new_users}</b>",
        f"⚙️ Сейчас в работе: <b>{active}</b>",
    ]
    if rating[0]:
        lines.append(f"⭐ Отзывы: <b>{float(rating[1]):.1f}</b> из 5 ({rating[0]})")
    if rows:
        lines.append("\n<b>По направлениям</b>")
        for kind, cnt, amount, profit, with_cost in sorted(rows, key=lambda r: -r[2]):
            note = "" if with_cost == cnt else f" <i>(себестоимость у {with_cost} из {cnt})</i>"
            lines.append(f"{kind_name(kind)}: {cnt} шт · {money(amount)} · прибыль {money(profit)}{note}")
    buttons = [btn(("• " if k == period else "") + v, Adm(s="stat", v=k)) for k, v in PERIODS.items()]
    await show(target, "\n".join(lines), kb(buttons[:3], buttons[3:], [btn("⚙️ Админка", Adm(s="menu"))]))


@router.callback_query(Adm.filter(F.s == "stat"))
async def on_stats(cb: CallbackQuery, callback_data: Adm, session: AsyncSession) -> None:
    await view(cb, session, callback_data)
