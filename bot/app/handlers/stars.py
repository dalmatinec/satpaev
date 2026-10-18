from decimal import Decimal

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from ..cb import In, Nav, Shop
from ..db.models import User
from ..services import media, settings
from ..services.orders import client_order_kb, create_order, created_text
from ..states import StarsSt
from ..ui import back_menu, kb, mbtn, say, screen_kb, show
from ..utils import clean_username, h, money, num, round_up

router = Router(name="stars")
t = settings.t


def price_for(qty: int) -> tuple[Decimal, Decimal]:
    unit = Decimal(str(settings.star_tiers()[0][1]))
    for min_qty, price in settings.star_tiers():
        if qty >= min_qty:
            unit = Decimal(str(price))
    return unit, round_up(unit * qty)


def min_qty() -> int:
    """Минимум звёзд: первая строка сетки, но не дешевле минимального заказа."""
    qty = settings.star_tiers()[0][0]
    minimum = settings.min_order()
    for _ in range(10):
        unit, total = price_for(qty)
        if total >= minimum or unit <= 0:
            break
        qty = max(qty + 1, int((minimum / unit).to_integral_value(rounding="ROUND_CEILING")))
    return qty


async def stars_view(target) -> None:
    tiers = "\n".join(t("stars_tier", qty=num(q), price=num(p)) for q, p in settings.star_tiers())
    text = t("stars_screen", tiers=tiers, sla=h(settings.get("sla_stars")), min=num(min_qty()))
    b = InlineKeyboardBuilder()
    for q in settings.get("star_presets") or []:
        try:
            q = int(q)
        except (TypeError, ValueError):
            continue
        if q < min_qty():
            continue
        _, total = price_for(q)
        b.button(text=f"{num(q)} ⭐ · {money(total)}", callback_data=Shop(sec="stars", a="qty", v=str(q)))
    b.adjust(2)
    markup = screen_kb("stars", {"stars_custom": mbtn("stars_custom", Shop(sec="stars", a="custom")),
                                 "home": back_menu()[0]}, top=b.as_markup().inline_keyboard)
    await show(target, text, markup, photo=media.photo("stars"), edit=("stars_screen", "stars"))


@router.callback_query(Nav.filter(F.to == "stars"))
async def nav_stars(cb: CallbackQuery) -> None:
    await stars_view(cb)


async def ask_recipient(target, state: FSMContext, user: User, qty: int) -> None:
    await state.set_state(StarsSt.recipient)
    await state.update_data(qty=qty)
    _, total = price_for(qty)
    rows = []
    if user.username:
        rows.append([mbtn("stars_me", In(a="st_me"), username=user.username)])
    rows.append([mbtn("back", Nav(to="stars"))])
    await show(target, t("stars_recipient", qty=num(qty), total=money(total)), kb(*rows), edit=("stars_recipient", None))


@router.callback_query(Shop.filter((F.sec == "stars") & (F.a == "qty")))
async def pick_qty(cb: CallbackQuery, callback_data: Shop, state: FSMContext, user: User) -> None:
    await ask_recipient(cb, state, user, int(callback_data.v))


@router.callback_query(Shop.filter((F.sec == "stars") & (F.a == "custom")))
async def custom_qty(cb: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(StarsSt.qty)
    await show(cb, t("stars_custom", min=num(min_qty())), kb([mbtn("back", Nav(to="stars"))]), edit=("stars_custom", None))


@router.message(StarsSt.qty)
async def input_qty(message: Message, state: FSMContext, user: User) -> None:
    raw = (message.text or "").replace(" ", "")
    if not raw.isdigit() or int(raw) < min_qty() or int(raw) > 1_000_000:
        await say(message, t("stars_bad_qty", min=num(min_qty())))
        return
    await ask_recipient(message, state, user, int(raw))


async def confirm(target, state: FSMContext, recipient: str) -> None:
    data = await state.get_data()
    qty = int(data.get("qty", 0))
    unit, total = price_for(qty)
    await state.update_data(recipient=recipient)
    await state.set_state(StarsSt.confirm)
    await show(
        target,
        t("stars_confirm", qty=num(qty), recipient=h(recipient), unit=num(unit), total=money(total),
          sla=h(settings.get("sla_stars"))),
        kb([mbtn("confirm", In(a="st_ok"))], [mbtn("change", Nav(to="stars"))]),
        edit=("stars_confirm", None),
    )


@router.callback_query(StarsSt.recipient, In.filter(F.a == "st_me"))
async def recipient_me(cb: CallbackQuery, state: FSMContext, user: User) -> None:
    await confirm(cb, state, user.username or "")


@router.message(StarsSt.recipient)
async def input_recipient(message: Message, state: FSMContext) -> None:
    uname = clean_username(message.text)
    if not uname:
        await say(message, t("stars_bad_recipient"))
        return
    await confirm(message, state, uname)


@router.callback_query(StarsSt.confirm, In.filter(F.a == "st_ok"))
async def place(cb: CallbackQuery, state: FSMContext, session: AsyncSession, user: User) -> None:
    data = await state.get_data()
    await state.clear()
    qty = int(data.get("qty", 0))
    recipient = data.get("recipient", "")
    if qty < min_qty() or not recipient:
        await stars_view(cb)
        return
    unit, total = price_for(qty)
    order = await create_order(
        session, cb.bot, user, "stars", f"{qty} звёзд для @{recipient}",
        [["Количество", f"{num(qty)} ⭐"], ["Получатель", f"@{recipient}"], ["Цена за звезду", f"{num(unit)} ₸"]],
        total, {"qty": qty, "recipient": recipient},
    )
    await show(cb, created_text(order), client_order_kb(order), keep=True)

