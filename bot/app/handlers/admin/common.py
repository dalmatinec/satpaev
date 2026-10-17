"""Общая часть админки: фильтр, главное меню и универсальный ввод значений."""

from dataclasses import dataclass
from typing import Awaitable, Callable

from aiogram import Bot, F, Router
from aiogram.filters import Filter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...cb import Adm, AIn, Nav
from ...db.models import Order, Review
from ...services import settings
from ...services.posting import poster_status
from ...states import AdmSt
from ...ui import btn, kb, show

router = Router(name="admin_common")


class IsAdmin(Filter):
    async def __call__(self, event, is_admin: bool = False) -> bool:
        return is_admin


@dataclass(slots=True)
class Ctx:
    target: Message | CallbackQuery
    message: Message | None
    text: str | None
    data: dict
    session: AsyncSession
    state: FSMContext
    bot: Bot

    async def back(self) -> None:
        """Вернуться на экран, с которого начали ввод."""
        await self.state.clear()
        await open_screen(self, Adm.unpack(self.data["back"]))


OpHandler = Callable[[Ctx], Awaitable[None]]
OPS: dict[str, OpHandler] = {}
SCREENS: dict[str, Callable] = {}


def op(name: str):
    def deco(fn: OpHandler) -> OpHandler:
        OPS[name] = fn
        return fn
    return deco


def screen(section: str):
    """Регистрирует функцию экрана раздела, чтобы к нему можно было вернуться после ввода."""
    def deco(fn):
        SCREENS[section] = fn
        return fn
    return deco


async def open_screen(ctx: Ctx, cbd: Adm) -> None:
    fn = SCREENS.get(cbd.s)
    if fn is None:
        await admin_menu(ctx.target, ctx.session)
        return
    await fn(ctx.target, ctx.session, cbd)


async def ask(
    target: Message | CallbackQuery,
    state: FSMContext,
    op_name: str,
    prompt: str,
    back: Adm,
    skip: bool = False,
    **data,
) -> None:
    await state.set_state(AdmSt.input)
    await state.set_data({"op": op_name, "back": back.pack(), **data})
    rows = []
    if skip:
        rows.append([btn("➡️ Пропустить", AIn(a="skip"))])
    rows.append([btn("◀️ Отмена", back)])
    await show(target, prompt, kb(*rows))


@router.message(AdmSt.input)
async def on_input(message: Message, state: FSMContext, session: AsyncSession) -> None:
    data = await state.get_data()
    handler = OPS.get(data.get("op", ""))
    if handler is None:
        await state.clear()
        await admin_menu(message, session)
        return
    text = message.text if message.text is not None else message.caption
    await handler(Ctx(message, message, text, data, session, state, message.bot))


@router.callback_query(AdmSt.input, AIn.filter(F.a == "skip"))
async def on_skip(cb: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    data = await state.get_data()
    handler = OPS.get(data.get("op", ""))
    if handler is None:
        await state.clear()
        await admin_menu(cb, session)
        return
    await handler(Ctx(cb, None, None, data, session, state, cb.bot))


async def admin_menu(target, session: AsyncSession, cbd: Adm | None = None) -> None:
    attention = await session.scalar(
        select(func.count(Order.id)).where(Order.status.in_(("new", "paid")))
    ) or 0
    active = await session.scalar(
        select(func.count(Order.id)).where(Order.status.in_(("new", "quote", "wait_pay", "paid", "work")))
    ) or 0
    new_reviews = await session.scalar(select(func.count(Review.id)).where(Review.status == "new")) or 0
    online, state_txt, _ = await poster_status(session)
    orders_btn = f"📋 Заказы ({active})" + (f" 🔥{attention}" if attention else "")
    text = (
        f"⚙️ <b>Админка {settings.get('brand')}</b>\n\n"
        f"📋 Активных заказов: <b>{active}</b>, требуют внимания: <b>{attention}</b>\n"
        f"📝 Новых отзывов: <b>{new_reviews}</b>\n"
        f"📢 Постер канала: {state_txt}"
    )
    await show(target, text, kb(
        [btn(orders_btn, Adm(s="ord"))],
        [btn("💱 Курсы", Adm(s="rates")), btn("⭐ Звёзды", Adm(s="stars"))],
        [btn("🎁 Подарки", Adm(s="cat", v="gift")), btn("💎 Юзеры", Adm(s="cat", v="uname"))],
        [btn("🛠 Услуги", Adm(s="cat", v="service")), btn("🖼 Портфолио", Adm(s="cat", v="portfolio"))],
        [btn("📢 Канал", Adm(s="ch")), btn("📨 Рассылка", Adm(s="bc"))],
        [btn("👤 Клиенты", Adm(s="cl")), btn("📊 Статистика", Adm(s="stat"))],
        [btn(f"📝 Отзывы ({new_reviews})", Adm(s="rev")), btn("🧩 Ещё", Adm(s="more"))],
        [btn("🏠 Клиентское меню", Nav(to="menu"))],
    ))


SCREENS["menu"] = admin_menu


@router.callback_query(Adm.filter(F.s == "menu"))
async def cb_menu(cb: CallbackQuery, session: AsyncSession) -> None:
    await admin_menu(cb, session)


async def more_menu(target, session: AsyncSession, cbd: Adm | None = None) -> None:
    await show(target, "🧩 <b>Ещё</b>\n\nОформление бота и редкие настройки.", kb(
        [btn("✏️ Тексты", Adm(s="tx")), btn("🔘 Кнопки и меню", Adm(s="bt"))],
        [btn("🖼 Картинки", Adm(s="img")), btn("⚙️ Настройки", Adm(s="set"))],
        [btn("👥 Рефералы", Adm(s="ref")), btn("💾 Бэкапы", Adm(s="bk"))],
        [btn("◀️ Админка", Adm(s="menu"))],
    ))


SCREENS["more"] = more_menu


@router.callback_query(Adm.filter(F.s == "more"))
async def cb_more(cb: CallbackQuery, session: AsyncSession) -> None:
    await more_menu(cb, session)
