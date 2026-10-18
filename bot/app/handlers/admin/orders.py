from decimal import Decimal

from aiogram import F, Router
from aiogram.types import CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...cb import Adm, Shop
from ...db.models import Order, User
from ...services import orders as svc
from ...texts import strip_html
from ...services import settings
from ...ui import btn, kb, mbtn, pager, say, send_safe, show
from ...utils import h, money, parse_number
from .common import Ctx, ask, op, screen

router = Router(name="admin_orders")
PER_PAGE = 8

FILTERS = {
    "att": ("🔥 Внимание", ("new", "paid")),
    "active": ("⚙️ Активные", svc.ACTIVE),
    "done": ("✅ Выполненные", ("done",)),
    "canceled": ("❌ Отменённые", ("canceled",)),
    "all": ("📚 Все", None),
}


@screen("ord")
async def view(target, session: AsyncSession, cbd: Adm) -> None:
    if cbd.a == "card":
        await card(target, session, cbd.i)
        return
    if cbd.a == "stages":
        await stages(target, session, cbd.i)
        return
    flt = cbd.v if cbd.v in FILTERS else "active"
    title, statuses = FILTERS[flt]
    q = select(Order)
    cq = select(func.count(Order.id))
    if statuses:
        q = q.where(Order.status.in_(statuses))
        cq = cq.where(Order.status.in_(statuses))
    total = await session.scalar(cq) or 0
    pages = max(1, (total + PER_PAGE - 1) // PER_PAGE)
    page = max(0, min(cbd.p, pages - 1))
    rows = (await session.execute(q.order_by(Order.id.desc()).offset(page * PER_PAGE).limit(PER_PAGE))).scalars().all()
    b = InlineKeyboardBuilder()
    for key, (name, _) in FILTERS.items():
        mark = "• " if key == flt else ""
        b.button(text=mark + name, callback_data=Adm(s="ord", v=key))
    b.adjust(2)
    for o in rows:
        icon = svc.status_icon(o.status)
        b.row(btn(f"{icon} #{o.id} · {svc.kind_plain(o.kind)} · {money(o.amount) if o.amount else 'без цены'}",
                  Adm(s="ord", a="card", i=o.id)))
    pager(b, page, pages, lambda p: Adm(s="ord", v=flt, p=p))
    b.row(btn("⚙️ Админка", Adm(s="menu")))
    text = f"📋 <b>Заказы</b> · {title}: <b>{total}</b>"
    if not rows:
        text += "\n\nЗдесь пока пусто."
    await show(target, text, b.as_markup())


async def card(target, session: AsyncSession, order_id: int) -> None:
    order = await session.get(Order, order_id)
    if not order:
        await show(target, "Заказ не найден.", kb([btn("◀️ Заказы", Adm(s="ord"))]))
        return
    user = await session.get(User, order.user_id)
    await show(target, svc.admin_card(order, user), svc.admin_order_kb(order))


async def stages(target, session: AsyncSession, order_id: int) -> None:
    order = await session.get(Order, order_id)
    if not order:
        await card(target, session, order_id)
        return
    done = (order.details or {}).get("stages") or {}
    rows = [[btn(("✅ " if key in done else "") + strip_html(svc.stage_name(key)), Adm(s="ord", a="stage", i=order.id, v=key))]
            for key in svc.STAGE_KEYS]
    rows.append([btn("◀️ К заказу", Adm(s="ord", a="card", i=order.id))])
    await show(
        target,
        f"📍 <b>Этап заказа #{order.id}</b> · @{h((order.details or {}).get('username', ''))}\n\n"
        "🔒 Занят: бот напомнит, когда можно выставлять на аукцион.\n"
        "🔨 Аукцион: напомнит, когда аукцион закончится.\n"
        "📤 Передан: клиент увидит, что юзер у него.\n\n"
        "Клиент получает уведомление на каждом этапе.",
        kb(*rows),
    )


@router.callback_query(Adm.filter(F.s == "ord"))
async def on_orders(cb: CallbackQuery, callback_data: Adm, session: AsyncSession, state) -> None:
    a, oid = callback_data.a, callback_data.i
    if a in ("", "card", "stages"):
        await view(cb, session, callback_data)
        return
    order = await session.get(Order, oid)
    if not order:
        await view(cb, session, Adm(s="ord"))
        return
    if a == "work":
        await svc.set_status(session, cb.bot, order, "work")
        await card(cb, session, oid)
    elif a == "cancel":
        await show(cb, f"Точно отменить заказ #{oid}? Клиент получит уведомление.", kb(
            [btn("❌ Да, отменить", Adm(s="ord", a="cancel_ok", i=oid))],
            [btn("◀️ Нет", Adm(s="ord", a="card", i=oid))],
        ))
    elif a == "cancel_ok":
        await svc.set_status(session, cb.bot, order, "canceled")
        await card(cb, session, oid)
    elif a == "done":
        hint = f"Сумма заказа: {money(order.amount)}\n" if order.amount else ""
        await ask(cb, state, "ord_cost",
                  f"✅ <b>Завершение заказа #{oid}</b>\n\n{hint}Введите себестоимость в ₸, чтобы бот посчитал прибыль.\n"
                  "Или нажмите «Пропустить».",
                  Adm(s="ord", a="card", i=oid), skip=True, order_id=oid)
    elif a == "price":
        await ask(cb, state, "ord_price",
                  f"💵 Введите цену для заказа #{oid} в ₸.\nКлиент получит предложение с кнопками «Согласен» и «Отказаться».",
                  Adm(s="ord", a="card", i=oid), order_id=oid)
    elif a == "note":
        await ask(cb, state, "ord_note", f"📝 Заметка к заказу #{oid} (видна только вам):",
                  Adm(s="ord", a="card", i=oid), order_id=oid)
    elif a == "stage":
        await svc.set_stage(session, cb.bot, order, callback_data.v)
        await stages(cb, session, oid)
    else:
        await card(cb, session, oid)


@op("ord_cost")
async def op_cost(ctx: Ctx) -> None:
    order = await ctx.session.get(Order, int(ctx.data["order_id"]))
    cost = None
    if ctx.text is not None:
        cost = Decimal(0) if ctx.text.strip() == "0" else parse_number(ctx.text)
        if cost is None:
            await say(ctx.target, "Нужно число, например <code>28000</code>. Или нажмите «Пропустить».")
            return
    await ctx.state.clear()
    if order and order.status not in ("done", "canceled"):
        await svc.finalize(ctx.session, ctx.bot, order, cost)
    await card(ctx.target, ctx.session, int(ctx.data["order_id"]))


@op("ord_price")
async def op_price(ctx: Ctx) -> None:
    price = parse_number(ctx.text)
    if price is None:
        await say(ctx.target, "Нужно число, например <code>30500</code>:")
        return
    await ctx.state.clear()
    order = await ctx.session.get(Order, int(ctx.data["order_id"]))
    if order:
        order.amount = price
        order.status = "quote"
        await ctx.session.commit()
        await send_safe(
            ctx.bot, order.user_id,
            settings.t("quote_offer", id=order.id, card=svc.client_card(order)),
            kb([mbtn("agree", Shop(sec="ord", a="agree", i=order.id)),
                mbtn("decline", Shop(sec="ord", a="decline", i=order.id))]),
        )
    await card(ctx.target, ctx.session, int(ctx.data["order_id"]))


@op("ord_note")
async def op_note(ctx: Ctx) -> None:
    await ctx.state.clear()
    order = await ctx.session.get(Order, int(ctx.data["order_id"]))
    if order:
        order.details = {**(order.details or {}), "admin_note": (ctx.text or "")[:500]}
        await ctx.session.commit()
    await card(ctx.target, ctx.session, int(ctx.data["order_id"]))
