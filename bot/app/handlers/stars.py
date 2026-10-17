from decimal import Decimal

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from ..cb import In, Nav, Shop
from ..db.models import User
from ..services import settings
from ..services.orders import client_order_kb, create_order, created_text
from ..states import StarsSt
from ..ui import back_menu, btn, kb, show
from ..utils import clean_username, h, money, num, round_up

router = Router(name="stars")


def price_for(qty: int) -> tuple[Decimal, Decimal]:
    unit = Decimal("0")
    for min_qty, price in settings.star_tiers():
        if qty >= min_qty:
            unit = Decimal(str(price))
    if unit == 0:
        unit = Decimal(str(settings.star_tiers()[0][1]))
    return unit, round_up(unit * qty)


def min_qty() -> int:
    return settings.star_tiers()[0][0]


def stars_screen() -> tuple[str, object]:
    tiers = settings.star_tiers()
    lines = [f"• от <b>{num(q)}</b> шт: <b>{num(p)} ₸</b> за звезду" for q, p in tiers]
    text = (
        "⭐ <b>Звёзды Telegram</b>\n\n"
        "Чем больше берёте, тем дешевле звезда:\n" + "\n".join(lines) + "\n\n"
        f"⏱ Выдача: <b>{h(settings.get('sla_stars'))}</b>\n"
        f"📦 Минимум: <b>{num(min_qty())}</b> звёзд\n\n"
        "Выберите количество или введите своё 👇"
    )
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
    b.row(btn("✏️ Своё количество", Shop(sec="stars", a="custom")))
    b.row(*back_menu())
    return text, b.as_markup()


@router.callback_query(Nav.filter(F.to == "stars"))
async def nav_stars(cb: CallbackQuery) -> None:
    text, markup = stars_screen()
    await show(cb, text, markup)


async def ask_recipient(target, state: FSMContext, user: User, qty: int) -> None:
    await state.set_state(StarsSt.recipient)
    await state.update_data(qty=qty)
    unit, total = price_for(qty)
    rows = []
    if user.username:
        rows.append([btn(f"🙋 Себе (@{user.username})", In(a="st_me"))])
    rows.append([btn("◀️ Назад", Nav(to="stars"))])
    await show(
        target,
        f"⭐ <b>{num(qty)} звёзд</b> · {money(total)}\n\n"
        "Кому отправить? Напишите юзернейм получателя, например <code>@username</code>",
        kb(*rows),
    )


@router.callback_query(Shop.filter((F.sec == "stars") & (F.a == "qty")))
async def pick_qty(cb: CallbackQuery, callback_data: Shop, state: FSMContext, user: User) -> None:
    await ask_recipient(cb, state, user, int(callback_data.v))


@router.callback_query(Shop.filter((F.sec == "stars") & (F.a == "custom")))
async def custom_qty(cb: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(StarsSt.qty)
    await show(cb, f"✏️ Введите количество звёзд (минимум {num(min_qty())}):", kb([btn("◀️ Назад", Nav(to="stars"))]))


@router.message(StarsSt.qty)
async def input_qty(message: Message, state: FSMContext, user: User) -> None:
    raw = (message.text or "").replace(" ", "")
    if not raw.isdigit() or int(raw) < min_qty() or int(raw) > 1_000_000:
        await message.answer(f"Нужно целое число от {num(min_qty())}. Попробуйте ещё раз:")
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
        "🧾 <b>Проверьте заказ</b>\n\n"
        f"⭐ Количество: <b>{num(qty)}</b>\n"
        f"👤 Получатель: <b>@{h(recipient)}</b>\n"
        f"💰 Цена за звезду: {num(unit)} ₸\n"
        f"💳 К оплате: <b>{money(total)}</b>\n"
        f"⏱ Выдача: {h(settings.get('sla_stars'))}",
        kb([btn("✅ Оформить", In(a="st_ok"))], [btn("◀️ Изменить", Nav(to="stars"))]),
    )


@router.callback_query(StarsSt.recipient, In.filter(F.a == "st_me"))
async def recipient_me(cb: CallbackQuery, state: FSMContext, user: User) -> None:
    await confirm(cb, state, user.username or "")


@router.message(StarsSt.recipient)
async def input_recipient(message: Message, state: FSMContext) -> None:
    uname = clean_username(message.text)
    if not uname:
        await message.answer("Похоже, это не юзернейм. Пример: <code>@durov</code>")
        return
    await confirm(message, state, uname)


@router.callback_query(StarsSt.confirm, In.filter(F.a == "st_ok"))
async def place(cb: CallbackQuery, state: FSMContext, session: AsyncSession, user: User) -> None:
    data = await state.get_data()
    await state.clear()
    qty = int(data.get("qty", 0))
    recipient = data.get("recipient", "")
    if qty < min_qty() or not recipient:
        await nav_stars(cb)
        return
    unit, total = price_for(qty)
    order = await create_order(
        session, cb.bot, user, "stars", f"{qty} звёзд для @{recipient}",
        [["Количество", f"{num(qty)} ⭐"], ["Получатель", f"@{recipient}"], ["Цена за звезду", f"{num(unit)} ₸"]],
        total, {"qty": qty, "recipient": recipient},
    )
    await show(cb, created_text(order), client_order_kb(order))
