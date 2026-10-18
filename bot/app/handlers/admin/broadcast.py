"""Рассылки всем или по сегментам. Идёт в фоне, пользователей читает пачками (мало памяти)."""

import asyncio
import logging
import time
from datetime import timedelta

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import exists, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ...cb import Adm, AIn
from ...db.models import Order, User
from ...states import AdmSt
from ...ui import answer, btn, kb, show
from ...utils import utcnow
from .common import screen

log = logging.getLogger(__name__)
router = Router(name="admin_broadcast")

SEGMENTS = {
    "all": "👥 Все",
    "stars": "⭐ Покупали звёзды",
    "premium": "👑 Покупали Premium",
    "gift": "🎁 Покупали подарки",
    "uname": "💎 Покупали юзеры",
    "exchange": "💱 Делали обмен",
    "dev": "🛠 Заказывали разработку",
    "buyers": "🛒 Все покупатели",
    "noorders": "🆕 Без заказов",
    "inactive": "💤 Не заходили 30 дней",
    "vip": "👑 VIP",
}

_running: dict = {"task": None, "stop": False}


def segment_where(seg: str):
    base = User.is_blocked.is_(False)
    done = (Order.user_id == User.id) & (Order.status == "done")
    kinds = {"stars": ("stars",), "premium": ("premium",), "gift": ("gift",), "uname": ("uname_ready", "uname_custom"),
             "exchange": ("exchange",), "dev": ("dev",)}
    if seg in kinds:
        return base & exists(select(Order.id).where(done, Order.kind.in_(kinds[seg])))
    if seg == "buyers":
        return base & exists(select(Order.id).where(done))
    if seg == "noorders":
        return base & ~exists(select(Order.id).where(done))
    if seg == "inactive":
        return base & (User.last_seen < utcnow() - timedelta(days=30))
    if seg == "vip":
        return base & (User.tag == "vip")
    return base


@screen("bc")
async def view(target, session: AsyncSession, cbd: Adm) -> None:
    running = _running["task"] is not None and not _running["task"].done()
    b = InlineKeyboardBuilder()
    if running:
        b.row(btn("⏹ Остановить текущую рассылку", Adm(s="bc", a="stop")))
    seg_buttons = [btn(name, Adm(s="bc", a="seg", v=key)) for key, name in SEGMENTS.items()]
    for i in range(0, len(seg_buttons), 2):
        b.row(*seg_buttons[i:i + 2])
    b.row(btn("⚙️ Админка", Adm(s="menu")))
    await show(target, "📨 <b>Рассылка</b>\n\nКому отправляем?" + ("\n\n⚠️ Сейчас идёт рассылка." if running else ""),
               b.as_markup())


@router.callback_query(Adm.filter(F.s == "bc"))
async def on_bc(cb: CallbackQuery, callback_data: Adm, session: AsyncSession, state: FSMContext) -> None:
    if callback_data.a == "seg" and callback_data.v in SEGMENTS:
        count = await session.scalar(select(func.count(User.id)).where(segment_where(callback_data.v))) or 0
        await state.set_state(AdmSt.broadcast)
        await state.set_data({"seg": callback_data.v, "count": count})
        await show(cb, f"📨 Сегмент: <b>{SEGMENTS[callback_data.v]}</b> · получателей: <b>{count}</b>\n\n"
                       "Пришлите сообщение для рассылки: текст, фото, видео, что угодно. "
                       "Премиум эмодзи сохранятся.", kb([btn("◀️ Отмена", Adm(s="bc"))]))
    elif callback_data.a == "stop":
        _running["stop"] = True
        await answer(cb, "Останавливаю...")
        await view(cb, session, callback_data)
    else:
        await view(cb, session, callback_data)


@router.message(AdmSt.broadcast)
async def bc_message(message: Message, state: FSMContext) -> None:
    await state.update_data(from_chat=message.chat.id, msg_id=message.message_id)
    await state.set_state(AdmSt.broadcast_confirm)
    data = await state.get_data()
    await message.answer("👀 Предпросмотр:")
    try:
        await message.copy_to(message.chat.id)
    except TelegramBadRequest:
        pass
    await message.answer(
        f"Отправить <b>{data['count']}</b> получателям ({SEGMENTS.get(data['seg'], '')})?",
        reply_markup=kb([btn("🚀 Запустить", AIn(a="bc_go"))], [btn("◀️ Отмена", Adm(s="bc"))]),
    )


@router.callback_query(AdmSt.broadcast_confirm, AIn.filter(F.a == "bc_go"))
async def bc_go(cb: CallbackQuery, state: FSMContext, session: AsyncSession, sm) -> None:
    data = await state.get_data()
    await state.clear()
    if _running["task"] is not None and not _running["task"].done():
        await answer(cb, "Уже идёт рассылка, дождитесь окончания", alert=True)
        return
    status = await show(cb, "🚀 Рассылка запущена...", kb([btn("⏹ Остановить", Adm(s="bc", a="stop"))]))
    _running["stop"] = False
    _running["task"] = asyncio.create_task(
        run(cb.bot, sm, data["seg"], data["from_chat"], data["msg_id"], cb.from_user.id, status.message_id if status else None)
    )


async def run(bot: Bot, sm, seg: str, from_chat: int, msg_id: int, admin_id: int, status_id: int | None) -> None:
    sent = failed = blocked = 0
    last_id = 0
    last_edit = time.monotonic()
    try:
        while not _running["stop"]:
            async with sm() as session:
                ids = (await session.execute(
                    select(User.id).where(segment_where(seg), User.id > last_id).order_by(User.id).limit(500)
                )).scalars().all()
            if not ids:
                break
            dead = []
            for uid in ids:
                if _running["stop"]:
                    break
                last_id = uid
                try:
                    await bot.copy_message(uid, from_chat, msg_id)
                    sent += 1
                except TelegramRetryAfter as e:
                    await asyncio.sleep(e.retry_after + 1)
                    try:
                        await bot.copy_message(uid, from_chat, msg_id)
                        sent += 1
                    except Exception:
                        failed += 1
                except TelegramForbiddenError:
                    blocked += 1
                    dead.append(uid)
                except TelegramBadRequest:
                    failed += 1
                await asyncio.sleep(0.05)
                if status_id and time.monotonic() - last_edit > 4:
                    last_edit = time.monotonic()
                    try:
                        await bot.edit_message_text(
                            f"🚀 Идёт рассылка...\n✅ {sent} · 🚫 {blocked} · ⚠️ {failed}",
                            chat_id=admin_id, message_id=status_id,
                            reply_markup=kb([btn("⏹ Остановить", Adm(s="bc", a="stop"))]),
                        )
                    except TelegramBadRequest:
                        pass
            if dead:
                async with sm() as session:
                    await session.execute(update(User).where(User.id.in_(dead)).values(is_blocked=True))
                    await session.commit()
    except Exception:
        log.exception("broadcast crashed")
    title = "⏹ Рассылка остановлена" if _running["stop"] else "✅ Рассылка завершена"
    try:
        await bot.send_message(admin_id, f"{title}\n\nДоставлено: <b>{sent}</b>\nЗаблокировали бота: <b>{blocked}</b>\nОшибок: <b>{failed}</b>",
                               reply_markup=kb([btn("⚙️ Админка", Adm(s="menu"))]))
    except (TelegramBadRequest, TelegramForbiddenError):
        pass


def start(bot: Bot, sm, seg: str, from_chat: int, msg_id: int, admin_id: int) -> bool:
    """Запуск рассылки из другого раздела (например, курсы). False, если уже идёт другая."""
    if _running["task"] is not None and not _running["task"].done():
        return False
    _running["stop"] = False
    _running["task"] = asyncio.create_task(run(bot, sm, seg, from_chat, msg_id, admin_id, None))
    return True
