from aiogram import F, Router
from aiogram.filters import Filter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...cb import Adm
from ...db.models import Order, RefAccrual, SupportLink, User
from ...services.orders import TAGS, kind_plain, status_icon, tag_name
from ...states import AdmSt
from ...ui import btn, kb, pager, say, show
from ...utils import clean_username, fdate, h, money
from ..support import deliver_to_user
from .common import Ctx, ask, op, screen

router = Router(name="admin_clients")
PER_PAGE = 8

LISTS = {"new": "🕑 Новые", "vip": "👑 VIP", "bad": "⚠️ Проблемные", "top": "💰 Топ по сумме", "ban": "🚫 Забаненные"}


@screen("cl")
async def view(target, session: AsyncSession, cbd: Adm) -> None:
    if cbd.a == "card":
        await card(target, session, cbd.i)
        return
    if cbd.a == "orders":
        await user_orders(target, session, cbd.i, cbd.p)
        return
    if cbd.a == "list" and cbd.v in LISTS:
        await user_list(target, session, cbd.v, cbd.p)
        return
    total = await session.scalar(select(func.count(User.id))) or 0
    blocked = await session.scalar(select(func.count(User.id)).where(User.is_blocked.is_(True))) or 0
    b = InlineKeyboardBuilder()
    b.row(btn("🔎 Найти клиента", Adm(s="cl", a="find")))
    for key, name in LISTS.items():
        b.button(text=name, callback_data=Adm(s="cl", a="list", v=key))
    b.adjust(1, 2, 2, 1)
    b.row(btn("⚙️ Админка", Adm(s="menu")))
    await show(target, f"👤 <b>Клиенты</b>\n\nВсего: <b>{total}</b> · заблокировали бота: <b>{blocked}</b>", b.as_markup())


async def user_list(target, session: AsyncSession, key: str, page: int) -> None:
    q = select(User)
    cq = select(func.count(User.id))
    where = {
        "vip": User.tag == "vip", "bad": User.tag == "bad", "ban": User.is_banned.is_(True),
        "top": User.total_spent > 0,
    }.get(key)
    if where is not None:
        q, cq = q.where(where), cq.where(where)
    order = User.total_spent.desc() if key == "top" else User.created_at.desc()
    total = await session.scalar(cq) or 0
    pages = max(1, (total + PER_PAGE - 1) // PER_PAGE)
    page = max(0, min(page, pages - 1))
    users = (await session.execute(q.order_by(order).offset(page * PER_PAGE).limit(PER_PAGE))).scalars().all()
    b = InlineKeyboardBuilder()
    for u in users:
        b.row(btn(f"{u.full_name[:24]} · {u.mention} · {money(u.total_spent)}", Adm(s="cl", a="card", i=u.id)))
    pager(b, page, pages, lambda p: Adm(s="cl", a="list", v=key, p=p))
    b.row(btn("◀️ Клиенты", Adm(s="cl")))
    await show(target, f"{LISTS[key]}: <b>{total}</b>", b.as_markup())


async def card(target, session: AsyncSession, user_id: int) -> None:
    u = await session.get(User, user_id)
    if not u:
        await show(target, "Клиент не найден.", kb([btn("◀️ Клиенты", Adm(s="cl"))]))
        return
    profit = await session.scalar(
        select(func.coalesce(func.sum(Order.amount - Order.cost), 0))
        .where(Order.user_id == u.id, Order.status == "done", Order.cost.is_not(None))
    )
    active = await session.scalar(
        select(func.count(Order.id)).where(Order.user_id == u.id, Order.status.in_(("new", "quote", "wait_pay", "paid", "work")))
    ) or 0
    invited = await session.scalar(select(func.count(User.id)).where(User.referrer_id == u.id)) or 0
    ref_unpaid = await session.scalar(
        select(func.coalesce(func.sum(RefAccrual.amount), 0)).where(RefAccrual.referrer_id == u.id, RefAccrual.paid.is_(False))
    )
    referrer = f"<code>{u.referrer_id}</code>" if u.referrer_id else "нет"
    text = (
        f"👤 <b>{h(u.full_name)}</b>\n{h(u.mention)} · <code>{u.id}</code>\n\n"
        f"🏷 Тег: <b>{tag_name(u.tag)}</b>{' · 🚫 БАН' if u.is_banned else ''}{' · бот заблокирован' if u.is_blocked else ''}\n"
        f"📅 С нами с {fdate(u.created_at, with_time=False)}, был {fdate(u.last_seen)}\n"
        f"📦 Выполнено заказов: <b>{u.orders_done}</b> · активных: <b>{active}</b>\n"
        f"💳 Потратил: <b>{money(u.total_spent)}</b> · прибыль с него: <b>{money(profit)}</b>\n"
        f"👥 Пригласил: <b>{invited}</b> · к выплате: <b>{money(ref_unpaid)}</b> · пришёл от: {referrer}"
    )
    if u.note:
        text += f"\n\n📝 {h(u.note)}"
    tag_row = [btn(("• " if u.tag == k else "") + v, Adm(s="cl", a="tag", i=u.id, v=k or "none")) for k, v in TAGS.items()]
    await show(target, text, kb(
        [btn("💬 Написать", Adm(s="cl", a="write", i=u.id)), btn("📦 Заказы", Adm(s="cl", a="orders", i=u.id))],
        tag_row,
        [btn("📝 Заметка", Adm(s="cl", a="note", i=u.id)),
         btn("✅ Разбанить" if u.is_banned else "🚫 Забанить", Adm(s="cl", a="ban", i=u.id))],
        [btn("◀️ Клиенты", Adm(s="cl")), btn("⚙️ Админка", Adm(s="menu"))],
    ))


async def user_orders(target, session: AsyncSession, user_id: int, page: int) -> None:
    total = await session.scalar(select(func.count(Order.id)).where(Order.user_id == user_id)) or 0
    pages = max(1, (total + PER_PAGE - 1) // PER_PAGE)
    page = max(0, min(page, pages - 1))
    orders = (await session.execute(
        select(Order).where(Order.user_id == user_id).order_by(Order.id.desc()).offset(page * PER_PAGE).limit(PER_PAGE)
    )).scalars().all()
    b = InlineKeyboardBuilder()
    for o in orders:
        icon = status_icon(o.status)
        b.row(btn(f"{icon} #{o.id} · {kind_plain(o.kind)} · {money(o.amount) if o.amount else 'без цены'}",
                  Adm(s="ord", a="card", i=o.id)))
    pager(b, page, pages, lambda p: Adm(s="cl", a="orders", i=user_id, p=p))
    b.row(btn("◀️ Клиент", Adm(s="cl", a="card", i=user_id)))
    await show(target, f"📦 Заказы клиента: <b>{total}</b>", b.as_markup())


@router.callback_query(Adm.filter(F.s == "cl"))
async def on_clients(cb: CallbackQuery, callback_data: Adm, session: AsyncSession, state: FSMContext) -> None:
    a, uid = callback_data.a, callback_data.i
    if a == "find":
        await ask(cb, state, "cl_find", "🔎 Введите id или @username клиента:", Adm(s="cl"))
    elif a == "write":
        await state.set_state(AdmSt.reply)
        await state.set_data({"user_id": uid})
        u = await session.get(User, uid)
        await show(cb, f"💬 Сообщение для {h(u.full_name if u else uid)} ({h(u.mention if u else '')}).\n\n"
                       "Пришлите текст, фото, файл или голосовое, бот перешлёт от своего имени.",
                   kb([btn("◀️ Отмена", Adm(s="cl", a="card", i=uid))]))
    elif a == "tag":
        u = await session.get(User, uid)
        if u:
            u.tag = "" if callback_data.v == "none" else callback_data.v
            await session.commit()
        await card(cb, session, uid)
    elif a == "ban":
        u = await session.get(User, uid)
        if u:
            u.is_banned = not u.is_banned
            await session.commit()
        await card(cb, session, uid)
    elif a == "note":
        await ask(cb, state, "cl_note", "📝 Заметка о клиенте (видна только вам). «Пропустить» очистит заметку.",
                  Adm(s="cl", a="card", i=uid), skip=True, user_id=uid)
    else:
        await view(cb, session, callback_data)


@op("cl_find")
async def op_find(ctx: Ctx) -> None:
    raw = (ctx.text or "").strip()
    user = None
    if raw.lstrip("-").isdigit():
        user = await ctx.session.get(User, int(raw))
    else:
        uname = clean_username(raw)
        if uname:
            user = await ctx.session.scalar(select(User).where(User.username == uname))
        else:
            user = await ctx.session.scalar(
                select(User).where(or_(User.full_name.ilike(f"%{raw[:50]}%"))).order_by(User.last_seen.desc()).limit(1)
            )
    if not user:
        await say(ctx.target, "Не нашёл. Введите id, @username или имя:")
        return
    await ctx.state.clear()
    await card(ctx.target, ctx.session, user.id)


@op("cl_note")
async def op_note(ctx: Ctx) -> None:
    await ctx.state.clear()
    u = await ctx.session.get(User, int(ctx.data["user_id"]))
    if u:
        u.note = (ctx.text or "")[:1000]
        await ctx.session.commit()
    await card(ctx.target, ctx.session, int(ctx.data["user_id"]))


@router.message(AdmSt.reply)
async def reply_message(message: Message, state: FSMContext, session: AsyncSession) -> None:
    data = await state.get_data()
    await state.clear()
    uid = int(data.get("user_id") or 0)
    ok, err = await deliver_to_user(message.bot, message, uid)
    markup = kb([btn("💬 Ещё сообщение", Adm(s="cl", a="write", i=uid)), btn("👤 Клиент", Adm(s="cl", a="card", i=uid))])
    await say(message, "✅ Доставлено" if ok else f"⚠️ Не доставлено: {h(err)}", reply_markup=markup)


class SupportReply(Filter):
    """Реплай админа на пересланное сообщение клиента."""

    async def __call__(self, message: Message, session: AsyncSession) -> bool | dict:
        if not message.reply_to_message:
            return False
        uid = await session.scalar(select(SupportLink.user_id).where(
            SupportLink.admin_chat_id == message.chat.id,
            SupportLink.admin_msg_id == message.reply_to_message.message_id,
        ))
        return {"reply_user_id": uid} if uid else False


@router.message(SupportReply())
async def admin_reply(message: Message, reply_user_id: int) -> None:
    ok, err = await deliver_to_user(message.bot, message, reply_user_id)
    if ok:
        from ..support import _react

        await _react(message)
    else:
        await message.reply(f"⚠️ Не доставлено: {h(err)}")
