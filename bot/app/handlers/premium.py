"""Telegram Premium: 3, 6 или 12 месяцев. Цены в долларах, к оплате в тенге."""

from decimal import Decimal

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..cb import In, Nav, Shop
from ..db.models import Rate, User
from ..services import media, settings
from ..services.orders import client_order_kb, create_order, created_text
from ..states import PremSt
from ..ui import back_menu, kb, mbtn, say, screen_kb, show
from ..utils import clean_username, h, money, num, round_up

router = Router(name="premium")
t = settings.t

# курс доллара для Premium, если в админке не задан: продажа USDT из «💱 Курсы».
# Обновляется при каждом показе экрана и при старте бота (без запроса к базе на каждую кнопку).
_usdt_sell: dict = {"rate": Decimal(0)}


async def refresh_rate(session: AsyncSession) -> None:
    r = await session.scalar(select(Rate).where(func.upper(Rate.code) == "USDT", Rate.is_active.is_(True)))
    _usdt_sell["rate"] = Decimal(str(r.sell)) if r and r.sell else Decimal(0)


def usd_rate() -> Decimal:
    try:
        own = Decimal(str(settings.get("premium_usd") or 0))
    except Exception:
        own = Decimal(0)
    return own if own > 0 else _usdt_sell["rate"]


def plans() -> list[tuple[int, Decimal]]:
    out = []
    for row in settings.get("premium_plans") or []:
        try:
            months, usd = int(row[0]), Decimal(str(row[1]))
        except (TypeError, ValueError, IndexError):
            continue
        if months > 0 and usd > 0:
            out.append((months, usd))
    return out


def plan(months: int) -> Decimal | None:
    for m, usd in plans():
        if m == months:
            return usd
    return None


def period(months: int) -> str:
    if months % 12 == 0:
        years = months // 12
        return "1 год" if years == 1 else f"{years} года" if years < 5 else f"{years} лет"
    if months == 1:
        return "1 месяц"
    return f"{months} месяца" if months < 5 else f"{months} месяцев"


def price_kzt(usd: Decimal) -> Decimal | None:
    rate = usd_rate()
    return round_up(usd * rate) if rate > 0 else None


def kzt_text(usd: Decimal) -> str:
    kzt = price_kzt(usd)
    return money(kzt) if kzt else "цена в ₸ у менеджера"


async def premium_view(target, session: AsyncSession | None = None) -> None:
    if session is not None:
        await refresh_rate(session)
    items = plans()
    if not items:
        await show(target, t("premium_empty"), screen_kb("premium", {"home": back_menu()[0]}),
                   photo=media.photo("premium"), edit=("premium_empty", "premium"))
        return
    lines = "\n".join(t("premium_plan", period=period(m), usd=num(usd), kzt=kzt_text(usd)) for m, usd in items)
    b = InlineKeyboardBuilder()
    for m, usd in items:
        kzt = price_kzt(usd)
        b.button(text=f"👑 {period(m)} · {money(kzt) if kzt else f'{num(usd)} $'}",
                 callback_data=Shop(sec="prem", a="plan", v=str(m)))
    b.adjust(1)
    await show(target, t("premium_screen", plans=lines, sla=h(settings.get("sla_premium"))),
               screen_kb("premium", {"home": back_menu()[0]}, top=b.as_markup().inline_keyboard),
               photo=media.photo("premium"), edit=("premium_screen", "premium"))


@router.callback_query(Nav.filter(F.to == "premium"))
async def nav_premium(cb: CallbackQuery, session: AsyncSession) -> None:
    await premium_view(cb, session)


async def ask_recipient(target, state: FSMContext, user: User, months: int) -> bool:
    usd = plan(months)
    if usd is None:
        return False
    await state.set_state(PremSt.recipient)
    await state.update_data(months=months)
    rows = []
    if user.username:
        rows.append([mbtn("premium_me", In(a="pr_me"), username=user.username)])
    rows.append([mbtn("back", Nav(to="premium"))])
    await show(target, t("premium_recipient", period=period(months), kzt=kzt_text(usd)), kb(*rows),
               edit=("premium_recipient", None))
    return True


@router.callback_query(Shop.filter((F.sec == "prem") & (F.a == "plan")))
async def pick_plan(cb: CallbackQuery, callback_data: Shop, state: FSMContext, user: User, session: AsyncSession) -> None:
    await refresh_rate(session)
    if not await ask_recipient(cb, state, user, int(callback_data.v or 0)):
        await premium_view(cb, session)


async def confirm(target, state: FSMContext, recipient: str) -> None:
    data = await state.get_data()
    months = int(data.get("months") or 0)
    usd = plan(months)
    if usd is None:
        await premium_view(target)
        return
    await state.update_data(recipient=recipient)
    await state.set_state(PremSt.confirm)
    await show(
        target,
        t("premium_confirm", period=period(months), recipient=h(recipient), kzt=kzt_text(usd), usd=num(usd),
          sla=h(settings.get("sla_premium"))),
        kb([mbtn("confirm", In(a="pr_ok"))], [mbtn("change", Nav(to="premium"))]),
        edit=("premium_confirm", None),
    )


@router.callback_query(PremSt.recipient, In.filter(F.a == "pr_me"))
async def recipient_me(cb: CallbackQuery, state: FSMContext, user: User) -> None:
    await confirm(cb, state, user.username or "")


@router.message(PremSt.recipient)
async def input_recipient(message: Message, state: FSMContext) -> None:
    uname = clean_username(message.text)
    if not uname:
        await say(message, t("stars_bad_recipient"))
        return
    await confirm(message, state, uname)


@router.callback_query(PremSt.confirm, In.filter(F.a == "pr_ok"))
async def place(cb: CallbackQuery, state: FSMContext, session: AsyncSession, user: User) -> None:
    data = await state.get_data()
    await state.clear()
    months = int(data.get("months") or 0)
    recipient = data.get("recipient", "")
    usd = plan(months)
    if usd is None or not recipient:
        await premium_view(cb, session)
        return
    await refresh_rate(session)
    kzt = price_kzt(usd)  # None: курс не задан, менеджер назовёт цену в тенге
    details = [["Срок", period(months)], ["Получатель", f"@{recipient}"], ["Цена", f"{num(usd)} $"]]
    if kzt:
        details.append(["Курс $", f"{num(usd_rate())} ₸"])
    order = await create_order(
        session, cb.bot, user, "premium", f"Premium {period(months)} для @{recipient}",
        details, kzt, {"months": months, "usd": str(usd), "recipient": recipient},
    )
    await show(cb, created_text(order), client_order_kb(order), keep=True)
