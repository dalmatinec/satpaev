from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..cb import In, Nav, Shop
from ..db.models import Item, User
from ..services import settings
from ..services.orders import client_order_kb, create_order, created_text
from ..states import BuySt
from ..ui import back_menu, btn, kb, mbtn, show
from ..utils import h, money

router = Router(name="gifts")
t = settings.t


def _price(item: Item) -> str:
    return money(item.price) if item.price else t("price_on_request")


async def gift_page(target, session: AsyncSession, page: int) -> None:
    base = (Item.kind == "gift") & Item.is_active.is_(True)
    total = await session.scalar(select(func.count(Item.id)).where(base)) or 0
    if total == 0:
        await show(target, t("gifts_empty"), kb([mbtn("write_manager", Nav(to="support"))], back_menu()))
        return
    page = max(0, min(page, total - 1))
    item = (await session.execute(
        select(Item).where(base).order_by(Item.sort, Item.id.desc()).offset(page).limit(1)
    )).scalar_one()
    desc = f"\n{h(item.description)}\n" if item.description else ""
    text = t("gift_card", title=h(item.title), description=desc, price=_price(item), sla=h(settings.get("sla_gifts")))
    rows = []
    if total > 1:
        rows.append([
            btn("◀️", Shop(sec="gift", a="page", p=(page - 1) % total)),
            btn(f"{page + 1} из {total}", Shop(sec="gift", a="page", p=page)),
            btn("▶️", Shop(sec="gift", a="page", p=(page + 1) % total)),
        ])
    rows.append([mbtn("buy", Shop(sec="gift", a="buy", i=item.id))])
    if item.link.startswith("http"):
        rows.append([mbtn("gift_view", url=item.link)])
    rows.append(back_menu())
    await show(target, text, kb(*rows), photo=item.photo or None)


@router.callback_query(Nav.filter(F.to == "gifts"))
async def nav_gifts(cb: CallbackQuery, session: AsyncSession) -> None:
    await gift_page(cb, session, 0)


@router.callback_query(Shop.filter((F.sec == "gift") & (F.a == "page")))
async def gifts_page(cb: CallbackQuery, callback_data: Shop, session: AsyncSession) -> None:
    await gift_page(cb, session, callback_data.p)


@router.callback_query(Shop.filter((F.sec == "gift") & (F.a == "buy")))
async def gift_buy(cb: CallbackQuery, callback_data: Shop, session: AsyncSession, state: FSMContext) -> None:
    item = await session.get(Item, callback_data.i)
    if not item or not item.is_active:
        await show(cb, t("gift_sold"), kb([mbtn("to_gifts", Nav(to="gifts"))]))
        return
    await state.set_state(BuySt.confirm)
    await state.update_data(item_id=item.id)
    await show(
        cb,
        t("gift_confirm", title=h(item.title), price=_price(item)),
        kb([mbtn("confirm", In(a="buy_ok"))], [mbtn("back", Nav(to="gifts"))]),
    )


async def place_item(cb: CallbackQuery, state: FSMContext, session: AsyncSession, user: User) -> None:
    """Оформление заказа на позицию каталога (подарок или готовый юзер)."""
    from .usernames import ready_price  # избегаем циклического импорта

    data = await state.get_data()
    await state.clear()
    item = await session.get(Item, int(data.get("item_id") or 0))
    if not item or not item.is_active:
        await show(cb, t("gift_sold") if item and item.kind == "gift" else t("un_sold"), kb(back_menu()))
        return
    if item.kind == "gift":
        order = await create_order(
            session, cb.bot, user, "gift", item.title,
            [["Подарок", item.title]] + ([["Ссылка", item.link]] if item.link else []),
            item.price, item_id=item.id,
        )
    else:
        price_ton, price_kzt = ready_price(item)
        order = await create_order(
            session, cb.bot, user, "uname_ready", f"@{item.title}",
            [["Юзернейм", f"@{item.title}"], ["Цена", f"{price_ton} TON"]],
            price_kzt, {"username": item.title, "price_ton": price_ton}, item_id=item.id,
        )
    await show(cb, created_text(order), client_order_kb(order))


@router.callback_query(BuySt.confirm, In.filter(F.a == "buy_ok"))
async def buy_ok(cb: CallbackQuery, state: FSMContext, session: AsyncSession, user: User) -> None:
    await place_item(cb, state, session, user)
