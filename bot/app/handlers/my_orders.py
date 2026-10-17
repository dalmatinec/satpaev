from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..cb import Adm, In, Nav, Shop
from ..db.models import Order, Review, User
from ..services.orders import (
    STATUSES,
    admin_card,
    client_card,
    client_order_kb,
    kind_name,
    notify_admins,
    set_status,
)
from ..states import ReviewSt
from ..ui import back_menu, btn, kb, pager, show
from ..utils import h, money

router = Router(name="my_orders")
PER_PAGE = 8


@router.callback_query(Nav.filter(F.to == "orders"))
async def nav_orders(cb: CallbackQuery, callback_data: Nav, session: AsyncSession, user: User) -> None:
    total = await session.scalar(select(func.count(Order.id)).where(Order.user_id == user.id)) or 0
    if total == 0:
        await show(cb, "📦 У вас пока нет заказов.", kb(back_menu()))
        return
    pages = (total + PER_PAGE - 1) // PER_PAGE
    page = max(0, min(callback_data.p, pages - 1))
    orders = (await session.execute(
        select(Order).where(Order.user_id == user.id).order_by(Order.id.desc()).offset(page * PER_PAGE).limit(PER_PAGE)
    )).scalars().all()
    b = InlineKeyboardBuilder()
    for o in orders:
        status_icon = STATUSES.get(o.status, "").split(" ")[0]
        b.button(text=f"{status_icon} #{o.id} · {kind_name(o.kind)} · {money(o.amount) if o.amount else 'цена уточняется'}",
                 callback_data=Shop(sec="ord", a="card", i=o.id))
    b.adjust(1)
    pager(b, page, pages, lambda p: Nav(to="orders", p=p))
    b.row(*back_menu())
    await show(cb, f"📦 <b>Мои заказы</b> ({total})", b.as_markup())


async def _own(session: AsyncSession, user: User, order_id: int) -> Order | None:
    order = await session.get(Order, order_id)
    if order is None or order.user_id != user.id:
        return None
    return order


@router.callback_query(Shop.filter((F.sec == "ord") & (F.a == "card")))
async def order_card(cb: CallbackQuery, callback_data: Shop, session: AsyncSession, user: User) -> None:
    order = await _own(session, user, callback_data.i)
    if not order:
        await show(cb, "Заказ не найден.", kb(back_menu()))
        return
    await show(cb, client_card(order), client_order_kb(order))


@router.callback_query(Shop.filter((F.sec == "ord") & (F.a == "paid")))
async def order_paid(cb: CallbackQuery, callback_data: Shop, session: AsyncSession, user: User) -> None:
    order = await _own(session, user, callback_data.i)
    if not order or order.status != "wait_pay":
        await order_card(cb, callback_data, session, user)
        return
    await set_status(session, cb.bot, order, "paid", notify=False)
    await notify_admins(
        cb.bot,
        "💰 <b>Клиент отметил оплату</b>\n\n" + admin_card(order, user),
        kb([btn("📂 Открыть заказ", Adm(s="ord", a="card", i=order.id))]),
    )
    await show(cb, "✅ Спасибо! Менеджер проверит оплату и возьмёт заказ в работу.\n\n" + client_card(order),
               client_order_kb(order))


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
        from ..services import settings

        reply = "👍 Отлично! " + h(settings.rich("pay_info").text)
    else:
        await set_status(session, cb.bot, order, "canceled", notify=False)
        note = "✖️ Клиент отказался от цены"
        reply = "Заказ отменён. Если передумаете, просто оформите заново."
    await notify_admins(cb.bot, f"{note}\n\n" + admin_card(order, user),
                        kb([btn("📂 Открыть заказ", Adm(s="ord", a="card", i=order.id))]))
    await show(cb, reply + "\n\n" + client_card(order), client_order_kb(order))


# ---------- Отзыв после заказа ----------

@router.callback_query(Shop.filter((F.sec == "rev") & (F.a == "rate")))
async def review_rate(cb: CallbackQuery, callback_data: Shop, session: AsyncSession, user: User, state: FSMContext) -> None:
    order = await _own(session, user, callback_data.i)
    if not order or order.status != "done":
        await show(cb, "Отзыв можно оставить после выполнения заказа.", kb(back_menu()))
        return
    exists = await session.scalar(select(Review.id).where(Review.order_id == order.id))
    if exists:
        await show(cb, "Вы уже оставили отзыв на этот заказ, спасибо! 💛", kb(back_menu()))
        return
    rating = max(1, min(5, int(callback_data.v or 5)))
    await state.set_state(ReviewSt.text)
    await state.update_data(order_id=order.id, rating=rating)
    await show(cb, f"{'⭐' * rating}\n\nНапишите пару слов о заказе или нажмите «Без текста».",
               kb([btn("➡️ Без текста", In(a="rev_skip"))]))


async def _save_review(target, state: FSMContext, session: AsyncSession, user: User, text: str) -> None:
    data = await state.get_data()
    await state.clear()
    order_id = int(data.get("order_id") or 0)
    if not order_id or await session.scalar(select(Review.id).where(Review.order_id == order_id)):
        await show(target, "Спасибо! 💛", kb(back_menu()))
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
    await show(target, "💛 Спасибо за отзыв! Нам очень важно ваше мнение.", kb(back_menu()))


@router.callback_query(ReviewSt.text, In.filter(F.a == "rev_skip"))
async def review_skip(cb: CallbackQuery, state: FSMContext, session: AsyncSession, user: User) -> None:
    await _save_review(cb, state, session, user, "")


@router.message(ReviewSt.text)
async def review_text(message: Message, state: FSMContext, session: AsyncSession, user: User) -> None:
    await _save_review(message, state, session, user, (message.text or message.caption or "").strip())


@router.callback_query(Nav.filter(F.to == "reviews"))
async def nav_reviews(cb: CallbackQuery, session: AsyncSession) -> None:
    from ..services import settings

    stats = (await session.execute(
        select(func.count(Review.id), func.avg(Review.rating)).where(Review.status == "published")
    )).one()
    last = (await session.execute(
        select(Review).where(Review.status == "published", Review.text != "").order_by(Review.id.desc()).limit(5)
    )).scalars().all()
    text = "⭐ <b>Отзывы клиентов</b>\n\n"
    if stats[0]:
        text += f"Средняя оценка: <b>{float(stats[1]):.1f}</b> из 5 · отзывов: <b>{stats[0]}</b>\n\n"
    for r in last:
        text += f"{'⭐' * r.rating}\n«{h(r.text[:300])}»\n\n"
    if not stats[0]:
        text += "Отзывов пока нет, ваш может стать первым!"
    rows = []
    link = str(settings.get("reviews_link") or "")
    if link.startswith("http"):
        rows.append([btn("📢 Все отзывы в канале", url=link)])
    rows.append(back_menu())
    await show(cb, text.strip(), kb(*rows))
