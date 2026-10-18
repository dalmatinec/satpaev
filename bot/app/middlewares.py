import time
from datetime import timedelta
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, TelegramObject, User as TgUser

from .config import config
from .db import SessionMaker
from .db.models import User
from .utils import utcnow

SEEN_UPDATE = timedelta(minutes=10)


class AppMiddleware(BaseMiddleware):
    """Сессия базы на апдейт, пользователь, бан и антифлуд."""

    def __init__(self, session_maker: SessionMaker) -> None:
        self.sm = session_maker
        self._last: dict[int, float] = {}

    def _flood(self, uid: int) -> bool:
        now = time.monotonic()
        last = self._last.get(uid, 0.0)
        self._last[uid] = now
        if len(self._last) > 20000:  # не даём словарю расти бесконечно
            cutoff = now - 60
            self._last = {k: v for k, v in self._last.items() if v > cutoff}
        return now - last < 0.3

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        tg: TgUser | None = data.get("event_from_user")
        is_admin = bool(tg and tg.id in config.admin_ids)
        data["is_admin"] = is_admin
        if tg and not is_admin and self._flood(tg.id):
            return None
        async with self.sm() as session:
            data["session"] = session
            if tg and not tg.is_bot:
                user, is_new = await self._user(session, tg)
                if user.is_banned and not is_admin:
                    await session.commit()
                    return None
                data["user"] = user
                data["is_new_user"] = is_new
            try:
                result = await handler(event, data)
            except Exception:
                await session.rollback()
                raise
            await session.commit()
            return result

    @staticmethod
    async def _user(session, tg: TgUser) -> tuple[User, bool]:
        now = utcnow()
        uname = (tg.username or "").lower() or None
        name = (tg.full_name or "")[:256]
        user = await session.get(User, tg.id)
        if user is None:
            user = User(id=tg.id, username=uname, full_name=name, created_at=now, last_seen=now)
            session.add(user)
            await session.flush()
            return user, True
        last = user.last_seen
        if last is not None and last.tzinfo is None:
            last = last.replace(tzinfo=now.tzinfo)
        if user.username != uname or user.full_name != name or user.is_blocked or not last or now - last > SEEN_UPDATE:
            user.username = uname
            user.full_name = name
            user.is_blocked = False
            user.last_seen = now
        return user, False


class ResetStateMiddleware(BaseMiddleware):
    """Любая кнопка навигации сбрасывает незаконченный ввод."""

    async def __call__(self, handler, event: CallbackQuery, data: dict[str, Any]) -> Any:
        state: FSMContext | None = data.get("state")
        payload = event.data or ""
        if state is not None and not payload.startswith(("in:", "ai:")):
            if await state.get_state() is not None:
                await state.clear()
        return await handler(event, data)


# состояния, в которых сообщение клиента или админа нужно только боту: после обработки его можно убрать
_CLEAN_STATES = ("StarsSt:", "PremSt:", "ExSt:", "UnSt:", "DevSt:", "BuySt:", "ReviewSt:", "AdmSt:input", "AdmSt:wizard")
_CLEAN_COMMANDS = ("/start", "/menu", "/admin", "/edit")


class CleanInputMiddleware(BaseMiddleware):
    """Чистый чат: команды, кнопка «Главное меню» и ответы на вопросы бота удаляются после обработки.

    Переписка с менеджером, посты и рассылки не трогаются: там сообщение клиента или админа важно.
    """

    async def __call__(self, handler, event: Message, data: dict[str, Any]) -> Any:
        if event.chat.type != "private":
            return await handler(event, data)
        clean = False
        text = (event.text or "").strip()
        if text.startswith(_CLEAN_COMMANDS):
            clean = True
        else:
            state = data.get("state")
            current = await state.get_state() if state is not None else None
            if current and current.startswith(_CLEAN_STATES):
                clean = True
            elif text:
                from .handlers import menu_button

                user = data.get("user")
                clean = text == menu_button.label() or bool(user and user.menu_kb and text == user.menu_kb)
        result = await handler(event, data)
        bot = data.get("bot")
        if clean and bot is not None:
            try:
                await bot.delete_message(event.chat.id, event.message_id)
            except Exception:
                pass
        return result
