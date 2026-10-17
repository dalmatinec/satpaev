from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..cb import Adm, In, Nav, Shop
from ..db.models import Order, Review, User
from ..services import settings
from ..services.orders import (
    admin_card,
    client_card,
    client_order_kb,
    kind_plain,
    notify_admins,
    set_status,
    status_icon,
)
from ..states import ReviewSt
from ..ui import back_menu, btn, kb, mbtn, pager, show
from ..utils import h, money

router = Router(name="my_orders")
PER_PAGE = 8
t = settings.t


async def orders_view(target, session: AsyncSession, user: User, page: int) -> None:
    total = await session.scalar(select(func.count(Order.id)).where(Order.user_id == user.id)) or 0
    if total == 0:
        await show(target, t("orders_empty"), kb(back_menu()))
        return
    pages = (total + PER_PAGE - 1) // PER_PAGE
    page = max(0, min(page, pages - 1))
    orders = (await session.execute(
        select(Order).where(Order.user_id == user.id).order_by(Order.id.desc()).offset(page * PER_PAGE).limit(PER_PAGE)
    )).scalars().all()
    b = InlineKeyboardBuilder()
    for o in orders:
        price = money(o.amount) if o.amount else "цена уточняется"
        b.button(text=f"{status_icon(o.status)} #{o.id} · {kind_plain(o.kind)} · {price}",
                 callback_data=Shop(sec="ord", a="card", i=o.id))
    b.adjust(1)
    pager(b, page, pages, lambda p: Nav(to="orders", p=p))
    b.row(*back_menu())
    await show(target, t("orders_list", total=total), b.as_markup())


@router.callback_query(Nav.filter(F.to == "orders"))
async def nav_orders(cb: CallbackQuery, callback_data: Nav, session: AsyncSession, user: User) -> None:
    await orders_view(cb, session, user, callback_data.p)


async def _own(session: AsyncSession, user: User, order_id: int) -> Order | None:
    order = await session.get(Order, order_id)
    if order is None or order.user_id != user.id:
        return None
    return order


@router.callback_query(Shop.filter((F.sec == "ord") & (F.a == "card")))
async def order_card(cb: CallbackQuery, callback_data: Shop, session: AsyncSession, user: User) -> None:
    order = await _own(session, user, callback_data.i)
    if not order:
        await show(cb, t("order_not_found"), kb(back_menu()))
        return
    await show(cb, client_card(order), client_order_kb(order))


def _admin_open(order: Order):
    return kb([btn("📂 Открыть заказ", Adm(s="ord", a="card", i=order.id))])


@router.callback_query(Shop.filter((F.sec == "ord") & (F.a == "paid")))
async def order_paid(cb: CallbackQuery, callback_data: Shop, session: AsyncSession, user: User) -> None:
    order = await _own(session, user, callback_data.i)
    if not order or order.status != "wait_pay":
        await order_card(cb, callback_data, session, user)
        return
    await set_status(session, cb.bot, order, "paid", notify=False)
    await notify_admins(cb.bot, "💰 <b>Клиент отметил оплату</b>\n\n" + admin_card(order, user), _admin_open(order))
    await show(cb, t("paid_thanks", card=client_card(order)), client_order_kb(order))


@router.callback_query(Shop.filter((F.sec == "ord") & (F.a.in_({"agree", "decline"}))))
async def order_quote(cb: CallbackQuery, callback_data: Shop, session: AsyncSession, user: User) -> None:
    order = await _own(session, user, callback_data.i)
    if not order or order.status != "quote":
        if order:
            await show(cb, client_card(order), client_order_kb(order))
        return
    if callback_data.a == "agree":
        await set_status(session, cb.bot, order, "wait_pay", notify=False)
        note = "✅ Клиент согласился с ценой"
        reply = t("quote_agree", pay=t("pay_info"), card=client_card(order))
    else:
        await set_status(session, cb.bot, order, "canceled", notify=False)
        note = "✖️ Клиент отказался от цены"
        reply = t("quote_decline", card=client_card(order))
    await notify_admins(cb.bot, f"{note}\n\n" + admin_card(order, user), _admin_open(order))
    await show(cb, reply, client_order_kb(order))


# ---------- Отзыв после заказа ----------

@router.callback_query(Shop.filter((F.sec == "rev") & (F.a == "rate")))
async def review_rate(cb: CallbackQuery, callback_data: Shop, session: AsyncSession, user: User, state: FSMContext) -> None:
    order = await _own(session, user, callback_data.i)
    if not order or order.status != "done":
        await show(cb, t("review_only_done"), kb(back_menu()))
        return
    if await session.scalar(select(Review.id).where(Review.order_id == order.id)):
        await show(cb, t("review_exists"), kb(back_menu()))
        return
    rating = max(1, min(5, int(callback_data.v or 5)))
    await state.set_state(ReviewSt.text)
    await state.update_data(order_id=order.id, rating=rating)
    await show(cb, t("review_text_ask", stars="⭐" * rating), kb([mbtn("no_text", In(a="rev_skip"))]))


async def _save_review(target, state: FSMContext, session: AsyncSession, user: User, text: str) -> None:
    data = await state.get_data()
    await state.clear()
    order_id = int(data.get("order_id") or 0)
    if not order_id or await session.scalar(select(Review.id).where(Review.order_id == order_id)):
        await show(target, t("review_thanks"), kb(back_menu()))
        return
    review = Review(order_id=order_id, user_id=user.id, rating=int(data.get("rating") or 5), text=text[:1000])
    session.add(review)
    await session.commit()
    await notify_admins(
        target.bot,
        f"📝 <b>Новый отзыв</b> {'⭐' * review.rating}\nЗаказ #{order_id} · {h(user.full_name)} ({h(user.mention)})\n\n"
        f"{('«' + h(review.text) + '»') if review.text else 'без текста'}",
        kb([btn("📢 Опубликовать", Adm(s="rev", a="pub", i=review.id)),
            btn("🙈 Скрыть", Adm(s="rev", a="hide", i=review.id))]),
    )
    await show(target, t("review_thanks"), kb(back_menu()))


@router.callback_query(ReviewSt.text, In.filter(F.a == "rev_skip"))
async def review_skip(cb: CallbackQuery, state: FSMContext, session: AsyncSession, user: User) -> None:
    await _save_review(cb, state, session, user, "")


@router.message(ReviewSt.text)
async def review_text(message: Message, state: FSMContext, session: AsyncSession, user: User) -> None:
    await _save_review(message, state, session, user, (message.text or message.caption or "").strip())


@router.callback_query(Nav.filter(F.to == "reviews"))
async def nav_reviews(cb: CallbackQuery, session: AsyncSession) -> None:
    count, avg = (await session.execute(
        select(func.count(Review.id), func.avg(Review.rating)).where(Review.status == "published")
    )).one()
    last = (await session.execute(
        select(Review).where(Review.status == "published", Review.text != "").order_by(Review.id.desc()).limit(5)
    )).scalars().all()
    stats = t("reviews_stats", avg=f"{float(avg):.1f}", count=count) if count else ""
    items = "".join(f"{'⭐' * r.rating}\n«{h(r.text[:300])}»\n\n" for r in last)
    if not count:
        items = t("reviews_empty")
    rows = []
    link = str(settings.get("reviews_link") or "")
    if link.startswith("http"):
        rows.append([mbtn("reviews_channel", url=link)])
    rows.append(back_menu())
    await show(cb, t("reviews_screen", stats=stats, list=items).strip(), kb(*rows))
