import logging
from datetime import timedelta
from decimal import Decimal

from aiogram import Bot
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..cb import Adm, Nav, Shop
from ..config import config
from ..db.models import Item, Order, RefAccrual, Reminder, User
from ..texts import strip_html
from ..ui import btn, kb, mbtn, send_safe
from ..utils import fdate, h, money, utcnow
from . import settings, workhours

log = logging.getLogger(__name__)

KIND_KEYS = ("stars", "gift", "uname_ready", "uname_custom", "exchange", "dev")
STATUS_KEYS = ("new", "quote", "wait_pay", "paid", "work", "done", "canceled")
ACTIVE = ("new", "quote", "wait_pay", "paid", "work")
STAGE_KEYS = ("reserved", "auction", "transferred")


def kind_name(kind: str) -> str:
    return settings.t(f"kind_{kind}") if kind in KIND_KEYS else kind


def status_name(status: str) -> str:
    return settings.t(f"st_{status}") if status in STATUS_KEYS else status


def stage_name(stage: str) -> str:
    return settings.t(f"stage_{stage}") if stage in STAGE_KEYS else stage


def kind_plain(kind: str) -> str:
    return strip_html(kind_name(kind))


def status_icon(status: str) -> str:
    return strip_html(status_name(status)).split(" ")[0]


def _lines(order: Order) -> str:
    rows = (order.details or {}).get("lines") or []
    return "\n".join(f"{h(k)}: <b>{h(v)}</b>" for k, v in rows)


def timeline(order: Order) -> str:
    if order.kind != "uname_custom":
        return ""
    stages = (order.details or {}).get("stages") or {}
    out = ["", "<b>Ход заказа</b>", "✅ Заявка принята"]
    passed = True
    for key in STAGE_KEYS:
        name = stage_name(key)
        if key in stages:
            out.append(f"✅ {name} <i>({fdate_iso(stages[key])})</i>")
        elif passed and order.status not in ("done", "canceled"):
            out.append(f"⏳ {name}")
            passed = False
        else:
            out.append(f"▫️ {name}")
    return "\n".join(out)


def fdate_iso(value: str) -> str:
    from datetime import datetime

    try:
        return fdate(datetime.fromisoformat(value), with_time=False)
    except (TypeError, ValueError):
        return ""


def client_card(order: Order) -> str:
    parts = [
        f"📦 <b>Заказ #{order.id}</b> · {kind_name(order.kind)}",
        f"Статус: <b>{status_name(order.status)}</b>",
        "",
        _lines(order),
    ]
    if order.amount is not None:
        parts.append("\n" + settings.t("order_amount", amount=money(order.amount)))
    elif order.status == "new":
        parts.append("\n" + settings.t("order_wait_price"))
    parts.append(timeline(order))
    return "\n".join(p for p in parts if p is not None)


def admin_card(order: Order, user: User | None) -> str:
    who = "неизвестно"
    if user:
        who = f"{h(user.full_name)} ({h(user.mention)}) · <code>{user.id}</code>"
        if user.tag:
            who += f" · {tag_name(user.tag)}"
    parts = [
        f"📦 <b>Заказ #{order.id}</b> · {kind_name(order.kind)}",
        f"Статус: <b>{status_name(order.status)}</b>",
        f"Клиент: {who}",
        f"Создан: {fdate(order.created_at)}",
        "",
        _lines(order),
        "",
        f"Сумма: <b>{money(order.amount)}</b>",
    ]
    if order.cost is not None:
        parts.append(f"Себестоимость: {money(order.cost)} · Прибыль: <b>{money(order.profit)}</b>")
    if order.stage:
        parts.append(f"Этап: {stage_name(order.stage)}")
    note = (order.details or {}).get("admin_note")
    if note:
        parts.append(f"📝 {h(note)}")
    return "\n".join(parts)


TAGS = {"vip": "👑 VIP", "bad": "⚠️ Проблемный", "": "Обычный"}


def tag_name(tag: str) -> str:
    return TAGS.get(tag, tag)


def admin_order_kb(order: Order):
    rows = []
    if order.status in ("new", "quote", "wait_pay"):
        label = "💵 Изменить цену" if order.amount is not None else "💵 Указать цену"
        rows.append([btn(label, Adm(s="ord", a="price", i=order.id))])
    if order.status in ("new", "wait_pay", "paid", "quote"):
        rows.append([btn("▶️ В работу", Adm(s="ord", a="work", i=order.id))])
    if order.kind == "uname_custom" and order.status not in ("done", "canceled"):
        rows.append([btn("📍 Этап юзера", Adm(s="ord", a="stages", i=order.id))])
    if order.status not in ("done", "canceled"):
        rows.append([
            btn("✅ Выполнен", Adm(s="ord", a="done", i=order.id)),
            btn("❌ Отменить", Adm(s="ord", a="cancel", i=order.id)),
        ])
    rows.append([
        btn("💬 Написать", Adm(s="cl", a="write", i=order.user_id)),
        btn("👤 Клиент", Adm(s="cl", a="card", i=order.user_id)),
    ])
    rows.append([btn("📝 Заметка", Adm(s="ord", a="note", i=order.id))])
    rows.append([btn("◀️ Заказы", Adm(s="ord")), btn("⚙️ Админка", Adm(s="menu"))])
    return kb(*rows)


def client_order_kb(order: Order):
    rows = []
    if order.status == "wait_pay":
        rows.append([mbtn("paid", Shop(sec="ord", a="paid", i=order.id))])
    if order.status == "quote":
        rows.append([
            mbtn("agree", Shop(sec="ord", a="agree", i=order.id)),
            mbtn("decline", Shop(sec="ord", a="decline", i=order.id)),
        ])
    rows.append([mbtn("write_manager", Nav(to="support"))])
    rows.append([mbtn("my_orders", Nav(to="orders")), mbtn("home_short", Nav(to="menu"))])
    return kb(*rows)


async def notify_admins(bot: Bot, text: str, markup=None) -> None:
    for admin_id in config.admin_ids:
        await send_safe(bot, admin_id, text, markup)


async def create_order(
    session: AsyncSession,
    bot: Bot,
    user: User,
    kind: str,
    title: str,
    lines: list[list[str]],
    amount: Decimal | None,
    extra: dict | None = None,
    item_id: int | None = None,
) -> Order:
    details = {"lines": lines, **(extra or {})}
    order = Order(
        user_id=user.id,
        kind=kind,
        title=title[:256],
        details=details,
        amount=amount,
        item_id=item_id,
        status="wait_pay" if amount is not None else "new",
    )
    session.add(order)
    await session.commit()
    await notify_admins(
        bot,
        "🔔 <b>Новый заказ</b>\n\n" + admin_card(order, user),
        kb([btn("📂 Открыть заказ", Adm(s="ord", a="card", i=order.id))]),
    )
    return order


def created_text(order: Order) -> str:
    text = settings.t("order_created", card=client_card(order))
    if order.status == "wait_pay":
        text += "\n\n" + settings.t("pay_info")
    if not workhours.is_working():
        text += "\n\n" + settings.t("after_hours_note", time=h(settings.get("work_from")))
    return text


def open_kb(order: Order):
    return kb([mbtn("open_order", Shop(sec="ord", a="card", i=order.id))])


async def notify_client(bot: Bot, order: Order, text: str) -> None:
    await send_safe(bot, order.user_id, text, open_kb(order))


async def set_status(session: AsyncSession, bot: Bot, order: Order, status: str, notify: bool = True) -> None:
    order.status = status
    order.updated_at = utcnow()
    await session.commit()
    if notify:
        await notify_client(bot, order, settings.t(
            "order_status", id=order.id, kind=kind_name(order.kind), status=status_name(status)))


async def set_stage(session: AsyncSession, bot: Bot, order: Order, stage: str) -> None:
    now = utcnow()
    details = dict(order.details or {})
    stages = dict(details.get("stages") or {})
    stages[stage] = now.isoformat()
    details["stages"] = stages
    order.details = details
    order.stage = stage
    if order.status in ("new", "wait_pay", "paid", "quote"):
        order.status = "work"
    uname = details.get("username", "")
    if stage == "reserved":
        days = int(settings.get("uname_hold_days") or 7)
        session.add(Reminder(order_id=order.id, due_at=now + timedelta(days=days),
                             text=f"⏰ Юзер @{uname} (заказ #{order.id}): можно выставлять на аукцион"))
    elif stage == "auction":
        days = int(settings.get("uname_auction_days") or 7)
        session.add(Reminder(order_id=order.id, due_at=now + timedelta(days=days),
                             text=f"⏰ Аукцион @{uname} (заказ #{order.id}) завершается, проверь ставки"))
    await session.commit()
    await notify_client(bot, order, settings.t(
        "order_stage", id=order.id, kind=kind_name(order.kind), stage=stage_name(stage), timeline=timeline(order)))


async def finalize(session: AsyncSession, bot: Bot, order: Order, cost: Decimal | None) -> None:
    order.status = "done"
    order.cost = cost
    order.done_at = utcnow()
    user = await session.get(User, order.user_id)
    if user and order.amount is not None:
        user.orders_done = (user.orders_done or 0) + 1
        user.total_spent = (user.total_spent or 0) + order.amount
    elif user:
        user.orders_done = (user.orders_done or 0) + 1
    if order.item_id and order.kind in ("gift", "uname_ready"):
        await session.execute(update(Item).where(Item.id == order.item_id).values(is_active=False))
    # отменяем напоминания по заказу
    await session.execute(update(Reminder).where(Reminder.order_id == order.id).values(sent=True))
    accrual = await _referral(session, order, user)
    await session.commit()

    from .reviews import ask_review  # локальный импорт, чтобы не было цикла

    await notify_client(bot, order, settings.t("order_done", id=order.id, kind=kind_name(order.kind)))
    await ask_review(bot, order)
    if accrual and user:
        await send_safe(
            bot,
            accrual.referrer_id,
            settings.t("ref_accrued", amount=money(accrual.amount)),
        )


async def _referral(session: AsyncSession, order: Order, user: User | None) -> RefAccrual | None:
    if not user or not user.referrer_id:
        return None
    percent = Decimal(str(settings.get("ref_percent") or 0))
    if percent <= 0:
        return None
    base = order.profit if settings.get("ref_base") == "profit" else order.amount
    if base is None or base <= 0:
        return None
    exists = await session.scalar(select(RefAccrual.id).where(RefAccrual.order_id == order.id))
    if exists:
        return None
    accrual = RefAccrual(
        referrer_id=user.referrer_id,
        referral_id=user.id,
        order_id=order.id,
        amount=(base * percent / 100).quantize(Decimal("0.01")),
    )
    session.add(accrual)
    return accrual
