from decimal import Decimal

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..cb import In, Nav, Shop
from ..db.models import Item, User
from ..services import settings, username_check
from ..services.orders import client_order_kb, create_order, created_text
from ..states import BuySt, UnSt
from ..ui import back_menu, btn, kb, pager, show
from ..utils import clean_username, h, money, num, round_up

router = Router(name="usernames")
PER_PAGE = 8


def ready_price(item: Item) -> tuple[str, Decimal | None]:
    markup = Decimal(str(item.markup or settings.get("uname_markup") or 2))
    price_ton = (Decimal(str(item.cost_ton or 0)) * markup).quantize(Decimal("0.01"))
    ton_kzt = Decimal(str(settings.get("ton_kzt") or 0))
    price_kzt = round_up(price_ton * ton_kzt) if ton_kzt > 0 and price_ton > 0 else None
    return num(price_ton), price_kzt


@router.callback_query(Nav.filter(F.to == "un"))
async def nav_un(cb: CallbackQuery) -> None:
    await show(
        cb,
        "💎 <b>Юзернеймы Telegram</b>\n\n"
        "🛍 <b>Готовые</b>: юзеры уже у нас, передадим через Fragment сразу после оплаты.\n\n"
        "✍️ <b>Под заказ</b>: хотите конкретный юзер? Мы займём его, проведём через аукцион Fragment "
        "и передадим вам как коллекционный NFT. Обычно это около двух недель, "
        "ход заказа видно в разделе «Мои заказы».",
        kb(
            [btn("🛍 Готовые юзеры", Shop(sec="un", a="list"))],
            [btn("✍️ Заказать свой юзер", Shop(sec="un", a="wish"))],
            back_menu(),
        ),
    )


@router.callback_query(Shop.filter((F.sec == "un") & (F.a == "list")))
async def ready_list(cb: CallbackQuery, callback_data: Shop, session: AsyncSession) -> None:
    base = (Item.kind == "uname") & Item.is_active.is_(True)
    total = await session.scalar(select(func.count(Item.id)).where(base)) or 0
    if total == 0:
        await show(
            cb,
            "🛍 Готовых юзеров сейчас нет, скоро добавим новые.\nМожно заказать свой юзер под вас.",
            kb([btn("✍️ Заказать свой", Shop(sec="un", a="wish"))], [btn("◀️ Назад", Nav(to="un"))]),
        )
        return
    pages = (total + PER_PAGE - 1) // PER_PAGE
    page = max(0, min(callback_data.p, pages - 1))
    items = (await session.execute(
        select(Item).where(base).order_by(Item.sort, Item.id.desc()).offset(page * PER_PAGE).limit(PER_PAGE)
    )).scalars().all()
    b = InlineKeyboardBuilder()
    for it in items:
        price_ton, _ = ready_price(it)
        b.button(text=f"@{it.title} · {price_ton} TON", callback_data=Shop(sec="un", a="card", i=it.id))
    b.adjust(1)
    pager(b, page, pages, lambda p: Shop(sec="un", a="list", p=p))
    b.row(btn("◀️ Назад", Nav(to="un")))
    await show(cb, f"🛍 <b>Готовые юзернеймы</b> ({total})\n\nВыберите, чтобы посмотреть подробнее:", b.as_markup())


@router.callback_query(Shop.filter((F.sec == "un") & (F.a == "card")))
async def ready_card(cb: CallbackQuery, callback_data: Shop, session: AsyncSession) -> None:
    item = await session.get(Item, callback_data.i)
    if not item or not item.is_active or item.kind != "uname":
        await show(cb, "😔 Этот юзер уже продан.", kb([btn("◀️ К списку", Shop(sec="un", a="list"))]))
        return
    price_ton, price_kzt = ready_price(item)
    text = f"💎 <b>@{h(item.title)}</b>\n\n💰 Цена: <b>{price_ton} TON</b>"
    if price_kzt:
        text += f" (≈ {money(price_kzt)})"
    if item.description:
        text += f"\n\n{h(item.description)}"
    text += "\n\nПередача через Fragment, юзер станет вашим коллекционным NFT."
    await show(cb, text, kb(
        [btn("🛒 Купить", Shop(sec="un", a="buy", i=item.id))],
        [btn("🔗 Открыть на Fragment", url=f"https://fragment.com/username/{item.title}")],
        [btn("◀️ К списку", Shop(sec="un", a="list"))],
    ))


@router.callback_query(Shop.filter((F.sec == "un") & (F.a == "buy")))
async def ready_buy(cb: CallbackQuery, callback_data: Shop, session: AsyncSession, state: FSMContext) -> None:
    item = await session.get(Item, callback_data.i)
    if not item or not item.is_active:
        await show(cb, "😔 Этот юзер уже продан.", kb([btn("◀️ К списку", Shop(sec="un", a="list"))]))
        return
    price_ton, price_kzt = ready_price(item)
    await state.set_state(BuySt.confirm)
    await state.update_data(item_id=item.id)
    pay = f"{price_ton} TON" + (f" (≈ {money(price_kzt)})" if price_kzt else "")
    await show(
        cb,
        f"🧾 <b>Проверьте заказ</b>\n\n💎 @{h(item.title)}\n💳 К оплате: <b>{pay}</b>",
        kb([btn("✅ Оформить", In(a="buy_ok"))], [btn("◀️ Назад", Shop(sec="un", a="card", i=item.id))]),
    )


@router.callback_query(Shop.filter((F.sec == "un") & (F.a == "wish")))
async def wish(cb: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(UnSt.wish)
    await show(
        cb,
        "✍️ Напишите юзернейм, который хотите.\n\n"
        "Латиница, цифры и «_», от 4 до 32 символов. Например: <code>@cryptoking</code>",
        kb([btn("◀️ Назад", Nav(to="un"))]),
    )


@router.message(UnSt.wish)
async def wish_input(message: Message, state: FSMContext) -> None:
    uname = clean_username(message.text)
    if not uname:
        await message.answer("Такой юзернейм невозможен. Латиница, цифры и «_», от 4 символов. Попробуйте ещё:")
        return
    wait = await message.answer(f"🔎 Проверяю @{h(uname)}...")
    status = await username_check.check(uname)
    await state.set_state(UnSt.confirm)
    await state.update_data(username=uname, check=status)
    text = (
        f"💎 <b>@{h(uname)}</b>\n\n"
        f"Предварительная проверка: {h(status)}\n\n"
        "Отправьте заявку: менеджер проверит юзер и назовёт цену. Оплата только после согласия."
    )
    markup = kb(
        [btn("✅ Отправить заявку", In(a="un_ok"))],
        [btn("✏️ Другой юзер", Shop(sec="un", a="wish"))],
        [btn("◀️ Назад", Nav(to="un"))],
    )
    try:
        await wait.edit_text(text, reply_markup=markup)
    except Exception:
        await message.answer(text, reply_markup=markup)


@router.callback_query(UnSt.confirm, In.filter(F.a == "un_ok"))
async def wish_ok(cb: CallbackQuery, state: FSMContext, session: AsyncSession, user: User) -> None:
    data = await state.get_data()
    await state.clear()
    uname = data.get("username")
    if not uname:
        await nav_un(cb)
        return
    order = await create_order(
        session, cb.bot, user, "uname_custom", f"@{uname} под заказ",
        [["Юзернейм", f"@{uname}"], ["Проверка", data.get("check", "")]],
        None, {"username": uname, "stages": {}},
    )
    await show(cb, created_text(order), client_order_kb(order))
