"""Подписка на канал: проверка через getChatMember с коротким кэшем в памяти."""

import logging
import time

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError

from ..config import config
from . import settings

log = logging.getLogger(__name__)

OK_TTL = 15 * 60          # подтверждённую подписку не перепроверяем 15 минут
_ok: dict[int, float] = {}
_warned: dict[str, float] = {}
_pending: dict[int, str] = {}   # deep link, который клиент открыл до подписки
_recommended: dict[int, float] = {}

MEMBER = {"member", "administrator", "creator"}


def mode() -> str:
    m = settings.get("sub_mode")
    return m if m in ("off", "required", "recommend") else "off"


def channels() -> list[dict]:
    return [c for c in (settings.get("sub_channels") or []) if isinstance(c, dict) and c.get("chat")]


def _trim(d: dict, limit: int = 20000) -> None:
    if len(d) > limit:
        d.clear()


async def _warn(bot: Bot, chat: str, error: str) -> None:
    now = time.monotonic()
    if now - _warned.get(chat, 0) < 3600:
        return
    _warned[chat] = now
    log.warning("Проверка подписки на %s не работает: %s", chat, error)
    if config.owner_id:
        try:
            await bot.send_message(
                config.owner_id,
                f"⚠️ Не могу проверить подписку на {chat}: {error}\n"
                "Добавьте бота админом в канал. Пока проверка не работает, клиентов пропускаю.",
            )
        except (TelegramBadRequest, TelegramForbiddenError):
            pass


async def is_subscribed(bot: Bot, user_id: int, use_cache: bool = True) -> bool:
    chans = channels()
    if not chans:
        return True
    if use_cache and time.monotonic() - _ok.get(user_id, 0) < OK_TTL:
        return True
    for ch in chans:
        try:
            member = await bot.get_chat_member(ch["chat"], user_id)
        except (TelegramBadRequest, TelegramForbiddenError) as e:
            await _warn(bot, str(ch["chat"]), str(e))
            continue  # не можем проверить: не блокируем клиента
        status = getattr(member, "status", "")
        if status == "restricted" and getattr(member, "is_member", False):
            continue
        if status not in MEMBER:
            _ok.pop(user_id, None)
            return False
    _trim(_ok)
    _ok[user_id] = time.monotonic()
    return True


def remember_payload(user_id: int, payload: str) -> None:
    _trim(_pending, 5000)
    _pending[user_id] = payload


def pop_payload(user_id: int) -> str:
    return _pending.pop(user_id, "")


def should_recommend(user_id: int) -> bool:
    """Рекомендуем подписку не чаще раза в сутки."""
    now = time.monotonic()
    if now - _recommended.get(user_id, -1e9) < 86400:
        return False
    _trim(_recommended)
    _recommended[user_id] = now
    return True
