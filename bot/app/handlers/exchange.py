from decimal import Decimal

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..cb import In, Nav, Shop
from ..db.models import Rate, User
from ..services import settings
from ..services.orders import client_order_kb, create_order, created_text
from ..states import ExSt
from ..ui import back_menu, btn, kb, show
from ..utils import h, is_tenge_input, money, num, parse_number, round_up

router = Router(name="exchange")


def rate_line(r: Rate) -> str:
    parts = []
    if r.sell:
        parts.append(f"продаём <b>{num(r.sell)} ₸</b>")
    if r.buy:
        parts.append(f"покупаем <b>{num(r.buy)} ₸</b>")
    return f"• <b>{h(r.code)}</b>: " + " · ".join(parts)


@router.callback_query(Nav.filter(F.to == "ex"))
async def nav_ex(cb: CallbackQuery, session: AsyncSession) -> None:
    rates = (await session.execute(
        select(Rate).where(Rate.is_active.is_(True)).order_by(Rate.sort, Rate.id)
    )).scalars().all()
    rates = [r for r in rates if r.buy or r.sell]
    if not rates:
        await show(cb, "💱 <b>Обмен</b>\n\nКурсы обновляются, напишите менеджеру, он подскажет актуальный курс.",
                   kb([btn("💬 Написать менеджеру", Nav(to="support"))], back_menu()))
        return
    text = (
        "💱 <b>Обмен</b>\n\n" + "\n".join(rate_line(r) for r in rates) +
        f"\n\n⏱ Сделка: <b>{h(settings.get('sla_exchange'))}</b>\n\nВыберите валюту 👇"
    )
    b = InlineKeyboardBuilder()
    for r in rates:
        b.button(text=r.code, callback_data=Shop(sec="ex", a="pair", i=r.id))
    b.adjust(3)
    b.row(*back_menu())
    await show(cb, text, b.as_markup())


@router.callback_query(Shop.filter((F.sec == "ex") & (F.a == "pair")))
async def pair(cb: CallbackQuery, callback_data: Shop, session: AsyncSession) -> None:
    r = await session.get(Rate, callback_data.i)
    if not r or not r.is_active:
        await nav_ex(cb, session)
        return
    rows = []
    if r.sell:
        rows.append([btn(f"🟢 Купить {r.code} по {num(r.sell)} ₸", Shop(sec="ex", a="dir", i=r.id, v="buy"))])
    if r.buy:
        rows.append([btn(f"🔴 Продать {r.code} по {num(r.buy)} ₸", Shop(sec="ex", a="dir", i=r.id, v="sell"))])
    rows.append([btn("◀️ Назад", Nav(to="ex"))])
    await show(cb, f"💱 <b>{h(r.code)}</b>\n\n{rate_line(r)}\n\nЧто хотите сделать?", kb(*rows))


@router.callback_query(Shop.filter((F.sec == "ex") & (F.a == "dir")))
async def direction(cb: CallbackQuery, callback_data: Shop, session: AsyncSession, state: FSMContext) -> None:
    r = await session.get(Rate, callback_data.i)
    if not r:
        await nav_ex(cb, session)
        return
    await state.set_state(ExSt.amount)
    await state.update_data(rate_id=r.id, dir=callback_data.v)
    verb = "купить" if callback_data.v == "buy" else "продать"
    min_txt = f"\nМинимум: {num(r.min_qty)} {h(r.code)}" if r.min_qty else ""
    await show(
        cb,
        f"✏️ Сколько <b>{h(r.code)}</b> хотите {verb}?\n\n"
        f"Напишите число, например <code>60</code>.\nИли сумму в тенге: <code>30000 тг</code>{min_txt}",
        kb([btn("◀️ Назад", Shop(sec="ex", a="pair", i=r.id))]),
    )


@router.message(ExSt.amount)
async def amount_input(message: Message, state: FSMContext, session: AsyncSession) -> None:
    data = await state.get_data()
    r = await session.get(Rate, int(data.get("rate_id") or 0))
    value = parse_number(message.text)
    if not r or value is None:
        await message.answer("Не понял сумму. Пример: <code>60</code> или <code>30000 тг</code>")
        return
    side = data.get("dir")
    rate = r.sell if side == "buy" else r.buy
    if not rate:
        await message.answer("Курс сейчас недоступен, напишите менеджеру.")
        return
    rate = Decimal(str(rate))
    if is_tenge_input(message.text or ""):
        kzt = round_up(value)
        qty = (value / rate).quantize(Decimal("0.01"))
    else:
        qty = value
        kzt = round_up(value * rate)
    if r.min_qty and qty < r.min_qty:
        await message.answer(f"Минимум {num(r.min_qty)} {h(r.code)}. Введите сумму побольше:")
        return
    await state.update_data(qty=str(qty), kzt=str(kzt), rate=str(rate))
    await state.set_state(ExSt.confirm)
    if side == "buy":
        summary = f"🟢 Вы покупаете: <b>{num(qty)} {h(r.code)}</b>\n💳 Вы платите: <b>{money(kzt)}</b>"
    else:
        summary = f"🔴 Вы продаёте: <b>{num(qty)} {h(r.code)}</b>\n💰 Вы получаете: <b>{money(kzt)}</b>"
    await message.answer(
        "🧾 <b>Проверьте сделку</b>\n\n" + summary +
        f"\n📈 Курс: {num(rate)} ₸\n⏱ Сделка: {h(settings.get('sla_exchange'))}",
        reply_markup=kb([btn("✅ Оформить", In(a="ex_ok"))], [btn("◀️ Изменить", Shop(sec="ex", a="pair", i=r.id))]),
    )


@router.callback_query(ExSt.confirm, In.filter(F.a == "ex_ok"))
async def place(cb: CallbackQuery, state: FSMContext, session: AsyncSession, user: User) -> None:
    data = await state.get_data()
    await state.clear()
    r = await session.get(Rate, int(data.get("rate_id") or 0))
    if not r or "qty" not in data:
        await nav_ex(cb, session)
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
