"""Экран подписки на канал и проверка перед доступом к боту."""

from typing import Any

from aiogram import BaseMiddleware, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from ..cb import Sub
from ..db.models import User
from ..services import media, settings, subscription
from ..texts import strip_html
from ..ui import answer, mbtn, screen_kb, show

router = Router(name="subscribe")


async def sub_view(target, required: bool) -> None:
    top = []
    for ch in subscription.channels():
        url = ch.get("url") or ""
        if url.startswith("http"):
            top.append([mbtn("sub_channel", url=url, title=ch.get("title", ""))])
    buttons = {"sub_check": mbtn("sub_check", Sub(a="check"))} if required else {
        "sub_continue": mbtn("sub_continue", Sub(a="cont"))}
    key = "sub_required" if required else "sub_recommend"
    await show(target, settings.t(key), screen_kb("sub", buttons, top=top), photo=media.photo("sub"), edit=(key, "sub"))


async def _continue(cb: CallbackQuery, session: AsyncSession, state: FSMContext, user: User, is_admin: bool) -> None:
    from .start import deep_link, show_menu

    payload = subscription.pop_payload(user.id)
    if payload and isinstance(cb.message, Message) and await deep_link(payload, cb.message, state, session, user):
        return
    await show_menu(cb, user, is_admin)


@router.callback_query(Sub.filter(F.a == "check"))
async def sub_check(cb: CallbackQuery, session: AsyncSession, state: FSMContext, user: User, is_admin: bool) -> None:
    if await subscription.is_subscribed(cb.bot, user.id, use_cache=False):
        await answer(cb, strip_html(settings.t("sub_thanks")))
        await _continue(cb, session, state, user, is_admin)
    else:
        await answer(cb, strip_html(settings.t("sub_not_yet")), alert=True)


@router.callback_query(Sub.filter(F.a == "cont"))
async def sub_cont(cb: CallbackQuery, session: AsyncSession, state: FSMContext, user: User, is_admin: bool) -> None:
    await _continue(cb, session, state, user, is_admin)


class SubscriptionMiddleware(BaseMiddleware):
    """В режиме «обязательная» не пускает к боту без подписки (админов не трогает)."""

    async def __call__(self, handler, event, data: dict[str, Any]) -> Any:
        if data.get("is_admin") or subscription.mode() != "required" or not subscription.channels():
            return await handler(event, data)
        user = data.get("user")
        if user is None:
            return await handler(event, data)
        if isinstance(event, Message) and event.chat.type != "private":
            return await handler(event, data)
        if isinstance(event, CallbackQuery) and (event.data or "").startswith("sb:"):
            return await handler(event, data)
        bot = data["bot"]
        if await subscription.is_subscribed(bot, user.id):
            return await handler(event, data)
        if isinstance(event, Message) and (event.text or "").startswith("/start"):
            parts = event.text.split(maxsplit=1)
            payload = parts[1].strip() if len(parts) > 1 else ""
            if payload:
                if data.get("is_new_user"):
                    from .start import apply_referral

                    await apply_referral(data["session"], bot, user, payload)
                if not (payload[:1] == "r" and payload[1:].isdigit()):
                    subscription.remember_payload(user.id, payload)
        state: FSMContext | None = data.get("state")
        if state is not None:
            await state.clear()
        await sub_view(event, required=True)
        return None
