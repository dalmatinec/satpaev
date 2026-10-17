from decimal import Decimal

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..cb import In, Nav, Shop
from ..db.models import Rate, User
from ..services import media, settings
from ..services.orders import client_order_kb, create_order, created_text
from ..states import ExSt
from ..ui import back_menu, kb, mbtn, show
from ..utils import h, is_tenge_input, money, num, parse_number, round_up

router = Router(name="exchange")
t = settings.t


def rate_line(r: Rate) -> str:
    parts = []
    if r.sell:
        parts.append(t("ex_sell_part", rate=num(r.sell)))
    if r.buy:
        parts.append(t("ex_buy_part", rate=num(r.buy)))
    return t("ex_line", code=h(r.code), parts=" · ".join(parts))


async def ex_view(target, session: AsyncSession) -> None:
    rates = (await session.execute(
        select(Rate).where(Rate.is_active.is_(True)).order_by(Rate.sort, Rate.id)
    )).scalars().all()
    rates = [r for r in rates if r.buy or r.sell]
    if not rates:
        await show(target, t("ex_empty"), kb([mbtn("write_manager", Nav(to="support"))], back_menu()),
                   photo=media.photo("ex"))
        return
    text = t("ex_screen", rates="\n".join(rate_line(r) for r in rates), sla=h(settings.get("sla_exchange")))
    b = InlineKeyboardBuilder()
    for r in rates:
        b.button(text=r.code, callback_data=Shop(sec="ex", a="pair", i=r.id))
    b.adjust(3)
    b.row(*back_menu())
    await show(target, text, b.as_markup(), photo=media.photo("ex"))


@router.callback_query(Nav.filter(F.to == "ex"))
async def nav_ex(cb: CallbackQuery, session: AsyncSession) -> None:
    await ex_view(cb, session)


@router.callback_query(Shop.filter((F.sec == "ex") & (F.a == "pair")))
async def pair(cb: CallbackQuery, callback_data: Shop, session: AsyncSession) -> None:
    r = await session.get(Rate, callback_data.i)
    if not r or not r.is_active:
        await ex_view(cb, session)
        return
    rows = []
    if r.sell:
        rows.append([mbtn("ex_buy", Shop(sec="ex", a="dir", i=r.id, v="buy"), code=r.code, rate=num(r.sell))])
    if r.buy:
        rows.append([mbtn("ex_sell", Shop(sec="ex", a="dir", i=r.id, v="sell"), code=r.code, rate=num(r.buy))])
    rows.append([mbtn("back", Nav(to="ex"))])
    await show(cb, t("ex_pair", code=h(r.code), line=rate_line(r)), kb(*rows))


@router.callback_query(Shop.filter((F.sec == "ex") & (F.a == "dir")))
async def direction(cb: CallbackQuery, callback_data: Shop, session: AsyncSession, state: FSMContext) -> None:
    r = await session.get(Rate, callback_data.i)
    if not r:
        await ex_view(cb, session)
        return
    await state.set_state(ExSt.amount)
    await state.update_data(rate_id=r.id, dir=callback_data.v)
    verb = "купить" if callback_data.v == "buy" else "продать"
    min_txt = f"\nМинимум: {num(r.min_qty)} {h(r.code)}" if r.min_qty else ""
    await show(cb, t("ex_amount", code=h(r.code), verb=verb, min=min_txt),
               kb([mbtn("back", Shop(sec="ex", a="pair", i=r.id))]))


@router.message(ExSt.amount)
async def amount_input(message: Message, state: FSMContext, session: AsyncSession) -> None:
    data = await state.get_data()
    r = await session.get(Rate, int(data.get("rate_id") or 0))
    value = parse_number(message.text)
    if not r or value is None:
        await message.answer(t("ex_bad_amount"))
        return
    side = data.get("dir")
    rate = r.sell if side == "buy" else r.buy
    if not rate:
        await message.answer(t("ex_unavailable"))
        return
    rate = Decimal(str(rate))
    if is_tenge_input(message.text or ""):
        kzt = round_up(value)
        qty = (value / rate).quantize(Decimal("0.01"))
    else:
        qty = value
        kzt = round_up(value * rate)
    if r.min_qty and qty < r.min_qty:
        await message.answer(t("ex_min", min=num(r.min_qty), code=h(r.code)))
        return
    await state.update_data(qty=str(qty), kzt=str(kzt), rate=str(rate))
    await state.set_state(ExSt.confirm)
    key = "ex_confirm_buy" if side == "buy" else "ex_confirm_sell"
    await show(
        message,
        t(key, qty=num(qty), code=h(r.code), kzt=money(kzt), rate=num(rate), sla=h(settings.get("sla_exchange"))),
        kb([mbtn("confirm", In(a="ex_ok"))], [mbtn("change", Shop(sec="ex", a="pair", i=r.id))]),
    )


@router.callback_query(ExSt.confirm, In.filter(F.a == "ex_ok"))
async def place(cb: CallbackQuery, state: FSMContext, session: AsyncSession, user: User) -> None:
    data = await state.get_data()
    await state.clear()
    r = await session.get(Rate, int(data.get("rate_id") or 0))
    if not r or "qty" not in data:
        await ex_view(cb, session)
        return
    qty, kzt, rate = Decimal(data["qty"]), Decimal(data["kzt"]), Decimal(data["rate"])
    buy = data.get("dir") == "buy"
    op = "Покупка" if buy else "Продажа"
    order = await create_order(
        session, cb.bot, user, "exchange", f"{op} {num(qty)} {r.code}",
        [["Операция", f"{op} {num(qty)} {r.code}"], ["Курс", f"{num(rate)} ₸"],
         ["Клиент платит" if buy else "Клиент получает", money(kzt)]],
        kzt, {"code": r.code, "dir": data.get("dir"), "qty": str(qty), "rate": str(rate)},
    )
    await show(cb, created_text(order), client_order_kb(order))
