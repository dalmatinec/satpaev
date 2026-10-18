from decimal import Decimal

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..cb import In, Nav, Shop
from ..db.models import Item, User
from ..services import media, settings, username_check
from ..services.orders import client_order_kb, create_order, created_text
from ..states import BuySt, UnSt
from ..ui import back_menu, kb, mbtn, pager, screen_kb, show
from ..utils import clean_username, h, money, num, round_up

router = Router(name="usernames")
PER_PAGE = 8
t = settings.t


def ready_price(item: Item) -> tuple[str, Decimal | None]:
    markup = Decimal(str(item.markup or settings.get("uname_markup") or 2))
    price_ton = (Decimal(str(item.cost_ton or 0)) * markup).quantize(Decimal("0.01"))
    ton_kzt = Decimal(str(settings.get("ton_kzt") or 0))
    price_kzt = round_up(price_ton * ton_kzt) if ton_kzt > 0 and price_ton > 0 else None
    return num(price_ton), price_kzt


def _price_text(item: Item) -> str:
    price_ton, price_kzt = ready_price(item)
    return f"{price_ton} TON" + (f" (≈ {money(price_kzt)})" if price_kzt else "")


async def un_view(target) -> None:
    await show(target, t("un_screen"), screen_kb("un", {
        "un_ready": mbtn("un_ready", Shop(sec="un", a="list")),
        "un_wish": mbtn("un_wish", Shop(sec="un", a="wish")),
        "home": back_menu()[0],
    }), photo=media.photo("un"), edit=("un_screen", "un"))


@router.callback_query(Nav.filter(F.to == "un"))
async def nav_un(cb: CallbackQuery) -> None:
    await un_view(cb)


@router.callback_query(Shop.filter((F.sec == "un") & (F.a == "list")))
async def ready_list(cb: CallbackQuery, callback_data: Shop, session: AsyncSession) -> None:
    base = (Item.kind == "uname") & Item.is_active.is_(True)
    total = await session.scalar(select(func.count(Item.id)).where(base)) or 0
    if total == 0:
        await show(cb, t("un_ready_empty"), kb([mbtn("un_wish", Shop(sec="un", a="wish"))], [mbtn("back", Nav(to="un"))]))
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
    b.row(mbtn("back", Nav(to="un")))
    await show(cb, t("un_ready_list", total=total), b.as_markup())


@router.callback_query(Shop.filter((F.sec == "un") & (F.a == "card")))
async def ready_card(cb: CallbackQuery, callback_data: Shop, session: AsyncSession) -> None:
    item = await session.get(Item, callback_data.i)
    if not item or not item.is_active or item.kind != "uname":
        await show(cb, t("un_sold"), kb([mbtn("un_to_list", Shop(sec="un", a="list"))]))
        return
    desc = f"\n{h(item.description)}\n" if item.description else ""
    await show(cb, t("un_card", name=h(item.title), price=_price_text(item), description=desc), kb(
        [mbtn("buy", Shop(sec="un", a="buy", i=item.id))],
        [mbtn("un_fragment", url=f"https://fragment.com/username/{item.title}")],
        [mbtn("un_to_list", Shop(sec="un", a="list"))],
    ))


@router.callback_query(Shop.filter((F.sec == "un") & (F.a == "buy")))
async def ready_buy(cb: CallbackQuery, callback_data: Shop, session: AsyncSession, state: FSMContext) -> None:
    item = await session.get(Item, callback_data.i)
    if not item or not item.is_active:
        await show(cb, t("un_sold"), kb([mbtn("un_to_list", Shop(sec="un", a="list"))]))
        return
    await state.set_state(BuySt.confirm)
    await state.update_data(item_id=item.id)
    await show(
        cb,
        t("un_confirm", name=h(item.title), price=_price_text(item)),
        kb([mbtn("confirm", In(a="buy_ok"))], [mbtn("back", Shop(sec="un", a="card", i=item.id))]),
    )


@router.callback_query(Shop.filter((F.sec == "un") & (F.a == "wish")))
async def wish(cb: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(UnSt.wish)
    await show(cb, t("un_wish"), kb([mbtn("back", Nav(to="un"))]), edit=("un_wish", None))


async def check_and_confirm(message: Message, state: FSMContext, uname: str) -> None:
    wait = await message.answer(t("un_checking", name=h(uname)))
    status = await username_check.check(uname)
    await state.set_state(UnSt.confirm)
    await state.update_data(username=uname, check=status)
    text = t("un_wish_result", name=h(uname), status=h(status))
    markup = kb(
        [mbtn("un_send", In(a="un_ok"))],
        [mbtn("un_other", Shop(sec="un", a="wish"))],
        [mbtn("back", Nav(to="un"))],
    )
    try:
        await wait.edit_text(text, reply_markup=markup)
    except Exception:
        await show(message, text, markup)


@router.message(UnSt.wish)
async def wish_input(message: Message, state: FSMContext) -> None:
    uname = clean_username(message.text)
    if not uname:
        await message.answer(t("un_wish_bad"))
        return
    await check_and_confirm(message, state, uname)


@router.callback_query(UnSt.confirm, In.filter(F.a == "un_ok"))
async def wish_ok(cb: CallbackQuery, state: FSMContext, session: AsyncSession, user: User) -> None:
    data = await state.get_data()
    await state.clear()
    uname = data.get("username")
    if not uname:
        await un_view(cb)
        return
    order = await create_order(
        session, cb.bot, user, "uname_custom", f"@{uname} под заказ",
        [["Юзернейм", f"@{uname}"], ["Проверка", data.get("check", "")]],
        None, {"username": uname, "stages": {}},
    )
    await show(cb, created_text(order), client_order_kb(order))

