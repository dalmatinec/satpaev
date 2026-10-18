from datetime import timezone

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
from ..ui import back_menu, btn, kb, mbtn, pager, screen_kb, show
from ..services.reviews import name_html
from ..utils import fdate, h, money, utcnow

router = Router(name="my_orders")
PER_PAGE = 8
t = settings.t


async def orders_view(target, session: AsyncSession, user: User, page: int) -> None:
    total = await session.scalar(select(func.count(Order.id)).where(Order.user_id == user.id)) or 0
    if total == 0:
        await show(target, t("orders_empty"), kb(back_menu()), edit=("orders_empty", None))
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
    await show(target, t("orders_list", total=total), b.as_markup(), edit=("orders_list", None))


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
    await show(cb, client_card(order), client_order_kb(order), edit=(None, "order"))


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


# ---------- Отзывы ----------

FREE_REVIEW_DAYS = 7
REVIEWS_PER_PAGE = 5


def _stars_kb(order_id: int):
    stars = [btn("⭐" * n, Shop(sec="rev", a="rate", i=order_id, v=str(n))) for n in range(1, 6)]
    return kb(stars[4:5], stars[3:4], stars[:3], back_menu())


@router.callback_query(Shop.filter((F.sec == "rev") & (F.a == "write")))
async def review_write(cb: CallbackQuery, session: AsyncSession, user: User) -> None:
    """Кнопка «Оставить отзыв»: сначала по выполненному заказу без отзыва, иначе общий отзыв."""
    reviewed = select(Review.order_id).where(Review.user_id == user.id, Review.order_id.is_not(None))
    order_id = await session.scalar(
        select(Order.id).where(Order.user_id == user.id, Order.status == "done", Order.id.not_in(reviewed))
        .order_by(Order.id.desc()).limit(1)
    )
    if order_id:
        await show(cb, t("review_ask", id=order_id), _stars_kb(order_id))
        return
    if settings.get("reviews_mode") != "all":
        await show(cb, t("review_orders_only"), kb(back_menu()))
        return
    last = await session.scalar(select(func.max(Review.created_at)).where(Review.user_id == user.id))
    if last is not None:
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        left = FREE_REVIEW_DAYS - (utcnow() - last).days
        if left > 0:
            await show(cb, t("review_too_often", days=left), kb(back_menu()))
            return
    await show(cb, t("review_free_ask"), _stars_kb(0), edit=("review_free_ask", None))


@router.callback_query(Shop.filter((F.sec == "rev") & (F.a == "rate")))
async def review_rate(cb: CallbackQuery, callback_data: Shop, session: AsyncSession, user: User, state: FSMContext) -> None:
    order_id = callback_data.i or None
    if order_id:
        order = await _own(session, user, order_id)
        if not order or order.status != "done":
            await show(cb, t("review_only_done"), kb(back_menu()))
            return
        if await session.scalar(select(Review.id).where(Review.order_id == order.id)):
            await show(cb, t("review_exists"), kb(back_menu()))
            return
    elif settings.get("reviews_mode") != "all":
        await show(cb, t("review_orders_only"), kb(back_menu()))
        return
    rating = max(1, min(5, int(callback_data.v or 5)))
    await state.set_state(ReviewSt.text)
    await state.update_data(order_id=order_id or 0, rating=rating)
    await show(cb, t("review_text_ask", stars="⭐" * rating), kb([mbtn("no_text", In(a="rev_skip"))]))


async def _save_review(target, state: FSMContext, session: AsyncSession, user: User, text: str) -> None:
    data = await state.get_data()
    await state.clear()
    order_id = int(data.get("order_id") or 0) or None
    if order_id and await session.scalar(select(Review.id).where(Review.order_id == order_id)):
        await show(target, t("review_thanks"), kb(back_menu()))
        return
    review = Review(order_id=order_id, user_id=user.id, rating=int(data.get("rating") or 5), text=text[:1000])
    session.add(review)
    await session.commit()
    where = f"Заказ #{order_id}" if order_id else "Без заказа"
    await notify_admins(
        target.bot,
        f"📝 <b>Новый отзыв</b> {'⭐' * review.rating}\n{where} · {name_html(user)} ({h(user.mention)})\n\n"
        f"{('«' + h(review.text) + '»') if review.text else 'без текста'}",
        kb([btn("📢 Опубликовать", Adm(s="rev", a="pub", i=review.id)),
            btn("✅ Одобрить", Adm(s="rev", a="ok", i=review.id))],
           [btn("🙈 Скрыть", Adm(s="rev", a="hide", i=review.id)),
            btn("🗑 Удалить", Adm(s="rev", a="del", i=review.id))]),
    )
    await show(target, t("review_thanks"), kb(back_menu()))


@router.callback_query(ReviewSt.text, In.filter(F.a == "rev_skip"))
async def review_skip(cb: CallbackQuery, state: FSMContext, session: AsyncSession, user: User) -> None:
    await _save_review(cb, state, session, user, "")


@router.message(ReviewSt.text)
async def review_text(message: Message, state: FSMContext, session: AsyncSession, user: User) -> None:
    await _save_review(message, state, session, user, (message.text or message.caption or "").strip())


@router.callback_query(Nav.filter(F.to == "reviews"))
async def nav_reviews(cb: CallbackQuery, callback_data: Nav, session: AsyncSession) -> None:
    """Опубликованные отзывы по 5 на странице: читается только нужная страница, память не растёт."""
    count, avg = (await session.execute(
        select(func.count(Review.id), func.avg(Review.rating)).where(Review.status == "published")
    )).one()
    pages = max(1, (count + REVIEWS_PER_PAGE - 1) // REVIEWS_PER_PAGE)
    page = max(0, min(callback_data.p, pages - 1))
    rows = (await session.execute(
        select(Review, User).join(User, User.id == Review.user_id, isouter=True)
        .where(Review.status == "published").order_by(Review.created_at.desc())
        .offset(page * REVIEWS_PER_PAGE).limit(REVIEWS_PER_PAGE)
    )).all()
    stats = t("reviews_stats", avg=f"{float(avg):.1f}", count=count) if count else ""
    items = "\n".join(
        t("reviews_item", stars="⭐" * r.rating, name=name_html(u), date=fdate(r.created_at, with_time=False),
          text=f"«{h(r.text[:400])}»" if r.text else "")
        for r, u in rows
    ) or t("reviews_empty")
    top = []
    if pages > 1:
        nav = []
        if page > 0:
            nav.append(btn("◀️", Nav(to="reviews", p=page - 1)))
        nav.append(btn(f"{page + 1}/{pages}", Nav(to="reviews", p=page)))
        if page < pages - 1:
            nav.append(btn("▶️", Nav(to="reviews", p=page + 1)))
        top.append(nav)
    buttons = {"home": back_menu()[0], "review_write": mbtn("review_write", Shop(sec="rev", a="write"))}
    link = str(settings.get("reviews_link") or "")
    if link.startswith("http"):
        buttons["reviews_channel"] = mbtn("reviews_channel", url=link)
    await show(cb, t("reviews_screen", stats=stats, list=items).strip(), screen_kb("reviews", buttons, top=top),
               edit=("reviews_screen", "reviews"))
