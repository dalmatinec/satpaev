from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..catalog import BUDGETS, DEADLINES, DEV_CATS
from ..cb import In, Nav, Shop
from ..db.models import Item, User
from ..services import media, settings
from ..services.orders import client_order_kb, create_order, created_text
from ..states import DevSt
from ..ui import back_menu, btn, kb, mbtn, show
from ..utils import h

router = Router(name="dev")
t = settings.t

ACTIVE_SERVICE = (Item.kind == "service") & Item.is_active.is_(True)


async def dev_view(target, session: AsyncSession) -> None:
    counts = dict((await session.execute(
        select(Item.category, func.count(Item.id)).where(ACTIVE_SERVICE).group_by(Item.category)
    )).all())
    b = InlineKeyboardBuilder()
    for key, name in DEV_CATS.items():
        if counts.get(key):
            b.button(text=name, callback_data=Shop(sec="dev", a="cat", v=key))
    b.adjust(2)
    b.row(mbtn("dev_pf", Shop(sec="dev", a="pf")))
    b.row(mbtn("dev_order", Shop(sec="dev", a="order")))
    b.row(*back_menu())
    await show(target, t("dev_screen"), b.as_markup(), photo=media.photo("dev"))


@router.callback_query(Nav.filter(F.to == "dev"))
async def nav_dev(cb: CallbackQuery, session: AsyncSession) -> None:
    await dev_view(cb, session)


@router.callback_query(Shop.filter((F.sec == "dev") & (F.a == "cat")))
async def category(cb: CallbackQuery, callback_data: Shop, session: AsyncSession) -> None:
    items = (await session.execute(
        select(Item).where(ACTIVE_SERVICE, Item.category == callback_data.v).order_by(Item.sort, Item.id).limit(30)
    )).scalars().all()
    name = DEV_CATS.get(callback_data.v, "Услуги")
    lines = [f"▫️ <b>{h(it.title)}</b>\n{h(it.price_text)}" for it in items]
    b = InlineKeyboardBuilder()
    for it in items:
        b.button(text=it.title[:60], callback_data=Shop(sec="dev", a="srv", i=it.id))
    b.adjust(1)
    b.row(mbtn("back", Nav(to="dev")))
    await show(cb, f"{name}\n\n" + ("\n\n".join(lines) or t("dev_cat_empty")), b.as_markup())


@router.callback_query(Shop.filter((F.sec == "dev") & (F.a == "srv")))
async def service(cb: CallbackQuery, callback_data: Shop, session: AsyncSession) -> None:
    it = await session.get(Item, callback_data.i)
    if not it or not it.is_active:
        await dev_view(cb, session)
        return
    desc = f"\n{h(it.description)}" if it.description else ""
    await show(cb, t("dev_service", title=h(it.title), price=h(it.price_text), description=desc), kb(
        [mbtn("dev_order_srv", Shop(sec="dev", a="order", i=it.id))],
        [mbtn("back", Shop(sec="dev", a="cat", v=it.category))],
    ))


@router.callback_query(Shop.filter((F.sec == "dev") & (F.a == "pf")))
async def portfolio(cb: CallbackQuery, callback_data: Shop, session: AsyncSession) -> None:
    base = (Item.kind == "portfolio") & Item.is_active.is_(True)
    total = await session.scalar(select(func.count(Item.id)).where(base)) or 0
    if total == 0:
        await show(cb, t("pf_empty"), kb([mbtn("back", Nav(to="dev"))]))
        return
    page = max(0, min(callback_data.p, total - 1))
    it = (await session.execute(
        select(Item).where(base).order_by(Item.sort, Item.id.desc()).offset(page).limit(1)
    )).scalar_one()
    text = f"🖼 <b>{h(it.title)}</b>"
    if it.description:
        text += f"\n\n{h(it.description)}"
    rows = []
    if total > 1:
        rows.append([
            btn("◀️", Shop(sec="dev", a="pf", p=(page - 1) % total)),
            btn(f"{page + 1} из {total}", Shop(sec="dev", a="pf", p=page)),
            btn("▶️", Shop(sec="dev", a="pf", p=(page + 1) % total)),
        ])
    if it.link.startswith("http"):
        rows.append([mbtn("dev_pf_link", url=it.link)])
    rows.append([mbtn("dev_same", Shop(sec="dev", a="order"))])
    rows.append([mbtn("back", Nav(to="dev"))])
    await show(cb, text, kb(*rows), photo=it.photo or None)


@router.callback_query(Shop.filter((F.sec == "dev") & (F.a == "order")))
async def brief_start(cb: CallbackQuery, callback_data: Shop, session: AsyncSession, state: FSMContext) -> None:
    service_title = ""
    if callback_data.i:
        it = await session.get(Item, callback_data.i)
        service_title = it.title if it else ""
    await state.set_state(DevSt.task)
    await state.update_data(service=service_title)
    head = f"Услуга: <b>{h(service_title)}</b>\n\n" if service_title else ""
    await show(cb, t("dev_step1", service=head), kb([mbtn("cancel", Nav(to="dev"))]))


@router.message(DevSt.task)
async def brief_task(message: Message, state: FSMContext) -> None:
    text = (message.text or message.caption or "").strip()
    if len(text) < 5:
        await message.answer(t("dev_task_short"))
        return
    await state.update_data(task=text[:2000])
    await state.set_state(DevSt.budget)
    b = InlineKeyboardBuilder()
    for i, v in enumerate(BUDGETS):
        b.button(text=v, callback_data=In(a="dev_b", v=str(i)))
    b.adjust(1)
    await show(message, t("dev_step2"), b.as_markup())


async def _ask_deadline(target, state: FSMContext, budget: str) -> None:
    await state.update_data(budget=budget)
    await state.set_state(DevSt.deadline)
    b = InlineKeyboardBuilder()
    for i, v in enumerate(DEADLINES):
        b.button(text=v, callback_data=In(a="dev_d", v=str(i)))
    b.adjust(2)
    await show(target, t("dev_step3"), b.as_markup())


@router.callback_query(DevSt.budget, In.filter(F.a == "dev_b"))
async def brief_budget_btn(cb: CallbackQuery, callback_data: In, state: FSMContext) -> None:
    await _ask_deadline(cb, state, BUDGETS[int(callback_data.v) % len(BUDGETS)])


@router.message(DevSt.budget)
async def brief_budget_text(message: Message, state: FSMContext) -> None:
    await _ask_deadline(message, state, (message.text or "")[:100] or "не указан")


async def _confirm(target, state: FSMContext, deadline: str) -> None:
    await state.update_data(deadline=deadline)
    await state.set_state(DevSt.confirm)
    d = await state.get_data()
    service = f"🛠 Услуга: <b>{h(d['service'])}</b>\n" if d.get("service") else ""
    await show(
        target,
        t("dev_confirm", service=service, task=h(d.get("task")), budget=h(d.get("budget")), deadline=h(deadline)),
        kb([mbtn("dev_send", In(a="dev_ok"))], [mbtn("cancel", Nav(to="dev"))]),
    )


@router.callback_query(DevSt.deadline, In.filter(F.a == "dev_d"))
async def brief_deadline_btn(cb: CallbackQuery, callback_data: In, state: FSMContext) -> None:
    await _confirm(cb, state, DEADLINES[int(callback_data.v) % len(DEADLINES)])


@router.message(DevSt.deadline)
async def brief_deadline_text(message: Message, state: FSMContext) -> None:
    await _confirm(message, state, (message.text or "")[:100] or "не указаны")


@router.callback_query(DevSt.confirm, In.filter(F.a == "dev_ok"))
async def brief_ok(cb: CallbackQuery, state: FSMContext, session: AsyncSession, user: User) -> None:
    d = await state.get_data()
    await state.clear()
    if not d.get("task"):
        await dev_view(cb, session)
        return
    lines = []
    if d.get("service"):
        lines.append(["Услуга", d["service"]])
    lines += [["Задача", d["task"]], ["Бюджет", d.get("budget", "")], ["Сроки", d.get("deadline", "")]]
    order = await create_order(session, cb.bot, user, "dev", d.get("service") or "Заявка на разработку", lines, None)
    await show(cb, created_text(order), client_order_kb(order))
