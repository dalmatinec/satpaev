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
from ..ui import back_menu, kb, mbtn, say, screen_kb, show
from ..utils import h, is_tenge_input, money, num, parse_number, round_up

router = Router(name="exchange")
t = settings.t


def min_deal(r: Rate) -> Decimal:
    """Минимальная сделка в ₸: своя у валюты (поле «Минимум») или общий минимальный заказ, что больше."""
    own = Decimal(str(r.min_qty)) if r.min_qty else Decimal(0)
    return max(own, settings.min_order())


def fee() -> Decimal:
    """Фиксированный сбор за сделку обмена в тенге (0 = без сбора)."""
    try:
        return max(Decimal(str(settings.get("ex_fee") or 0)), Decimal(0))
    except Exception:
        return Decimal(0)


def fee_name() -> str:
    return str(settings.get("ex_fee_name") or "Сервисный сбор")


def fee_line(sign: str = "") -> str:
    f = fee()
    return t("ex_fee_line", name=h(fee_name()), fee=sign + money(f)) if f else ""


def _with_fee(text: str, line: str) -> str:
    """Если админ поменял текст и убрал {fee_line}, сбор всё равно должен быть виден клиенту."""
    if line and line.strip() and line.strip() not in text:
        return text.rstrip() + "\n" + line.strip()
    return text


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
        await show(target, t("ex_empty"), screen_kb("ex", {
            "write_manager": mbtn("write_manager", Nav(to="support")), "home": back_menu()[0]}),
            photo=media.photo("ex"), edit=("ex_empty", "ex"))
        return
    line = fee_line()
    if line:
        line = line.rstrip("\n") + " за сделку\n\n"
    text = _with_fee(t("ex_screen", rates="\n".join(rate_line(r) for r in rates), sla=h(settings.get("sla_exchange")),
                       fee_line=line), line)
    b = InlineKeyboardBuilder()
    for r in rates:
        b.button(text=r.code, callback_data=Shop(sec="ex", a="pair", i=r.id))
    b.adjust(3)
    markup = screen_kb("ex", {"write_manager": mbtn("write_manager", Nav(to="support")), "home": back_menu()[0]},
                       top=b.as_markup().inline_keyboard)
    await show(target, text, markup, photo=media.photo("ex"), edit=("ex_screen", "ex"))


@router.callback_query(Nav.filter(F.to == "ex"))
async def nav_ex(cb: CallbackQuery, session: AsyncSession) -> None:
    await ex_view(cb, session)


async def pair_view(target, r: Rate) -> None:
    rows = []
    if r.sell:
        rows.append([mbtn("ex_buy", Shop(sec="ex", a="dir", i=r.id, v="buy"), code=r.code, rate=num(r.sell))])
    if r.buy:
        rows.append([mbtn("ex_sell", Shop(sec="ex", a="dir", i=r.id, v="sell"), code=r.code, rate=num(r.buy))])
    rows.append([mbtn("back", Nav(to="ex"))])
    await show(target, t("ex_pair", code=h(r.code), line=rate_line(r)), kb(*rows), edit=("ex_pair", None))


@router.callback_query(Shop.filter((F.sec == "ex") & (F.a == "pair")))
async def pair(cb: CallbackQuery, callback_data: Shop, session: AsyncSession) -> None:
    r = await session.get(Rate, callback_data.i)
    if not r or not r.is_active:
        await ex_view(cb, session)
        return
    await pair_view(cb, r)


@router.callback_query(Shop.filter((F.sec == "ex") & (F.a == "dir")))
async def direction(cb: CallbackQuery, callback_data: Shop, session: AsyncSession, state: FSMContext) -> None:
    r = await session.get(Rate, callback_data.i)
    if not r:
        await ex_view(cb, session)
        return
    await state.set_state(ExSt.amount)
    await state.update_data(rate_id=r.id, dir=callback_data.v)
    verb = "купить" if callback_data.v == "buy" else "продать"
    min_txt = f"\nМинимальная сделка: {money(min_deal(r))}"
    await show(cb, t("ex_amount", code=h(r.code), verb=verb, min=min_txt),
               kb([mbtn("back", Shop(sec="ex", a="pair", i=r.id))]), edit=("ex_amount", None))


@router.message(ExSt.amount)
async def amount_input(message: Message, state: FSMContext, session: AsyncSession) -> None:
    data = await state.get_data()
    r = await session.get(Rate, int(data.get("rate_id") or 0))
    value = parse_number(message.text)
    if not r or value is None:
        await say(message, t("ex_bad_amount"))
        return
    side = data.get("dir")
    rate = r.sell if side == "buy" else r.buy
    if not rate:
        await say(message, t("ex_unavailable"))
        return
    rate = Decimal(str(rate))
    f = fee()
    buy = side == "buy"
    if is_tenge_input(message.text or ""):
        # сумма в тенге: при покупке это сколько клиент платит всего, при продаже сколько хочет получить
        total = round_up(value)
        gross = total - f if buy else total + f
        if gross <= 0:
            await say(message, t("min_order", min=money(settings.min_order())))
            return
        qty = (gross / rate).quantize(Decimal("0.01"))
    else:
        qty = value
    gross = round_up(qty * rate)
    kzt = gross + f if buy else gross - f
    # минимальная сделка в тенге: при покупке считаем всё, что платит клиент, при продаже сумму по курсу
    if (kzt if buy else gross) < min_deal(r) or kzt <= 0:
        await say(message, t("min_order", min=money(min_deal(r))))
        return
    await state.update_data(qty=str(qty), kzt=str(kzt), rate=str(rate), fee=str(f), gross=str(gross))
    await state.set_state(ExSt.confirm)
    key = "ex_confirm_buy" if buy else "ex_confirm_sell"
    line = fee_line("+" if buy else "−")
    text = t(key, qty=num(qty), code=h(r.code), kzt=money(kzt), rate=num(rate), sum=money(gross),
             fee_line=line, sla=h(settings.get("sla_exchange")))
    await show(
        message,
        _with_fee(text, line),
        kb([mbtn("confirm", In(a="ex_ok"))], [mbtn("change", Shop(sec="ex", a="pair", i=r.id))]),
        edit=(key, None),
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
    f = Decimal(data.get("fee") or 0)
    buy = data.get("dir") == "buy"
    op = "Покупка" if buy else "Продажа"
    details = [["Операция", f"{op} {num(qty)} {r.code}"], ["Курс", f"{num(rate)} ₸"]]
    if f:
        details += [["По курсу", money(Decimal(data.get("gross") or 0))], [fee_name(), money(f)]]
    details.append(["Клиент платит" if buy else "Клиент получает", money(kzt)])
    order = await create_order(
        session, cb.bot, user, "exchange", f"{op} {num(qty)} {r.code}", details,
        kzt, {"code": r.code, "dir": data.get("dir"), "qty": str(qty), "rate": str(rate), "fee": str(f)},
    )
    await show(cb, created_text(order), client_order_kb(order), keep=True)
