"""Конкурс: пост с кнопкой «Участвовать», рассылка клиентам, итоги по таймеру, перевыбор победителя."""

import asyncio
import logging
import random
import re
from datetime import datetime

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from aiogram.types import MessageEntity
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..cb import Cn
from ..config import config
from ..db.models import Contest, ContestEntry, User
from ..ui import btn, kb
from ..utils import Rich, entities_from_store, h, u16, utcnow
from .orders import notify_admins

log = logging.getLogger(__name__)
_tasks: set = set()
DATE_RE = re.compile(r"^\s*(\d{1,2})\.(\d{1,2})\s+(\d{1,2}):(\d{2})\s*$")
DEFAULT_RESULT = "🏆 Итоги конкурса! Победитель: {winner}. Поздравляем!"


def parse_deadline(raw: str | None) -> datetime | None:
    """«ДД.ММ ЧЧ:ММ» по времени Алматы. None, если формат неверный или время уже прошло."""
    m = DATE_RE.match(raw or "")
    if not m:
        return None
    day, month, hh, mm = (int(x) for x in m.groups())
    now = utcnow()
    try:
        dt = datetime(now.astimezone(config.tz).year, month, day, hh, mm, tzinfo=config.tz)
    except ValueError:
        return None
    return dt if dt > now else None


def deadline_text(c: Contest) -> str:
    return c.ends_at.astimezone(config.tz).strftime("%d.%m.%Y %H:%M")


def body(c: Contest) -> Rich:
    """Текст поста с сохранёнными премиум эмодзи и строкой с итогами (жирным)."""
    head = c.text or ""
    label = "\n\n⏳ Итоги: "
    when = deadline_text(c)
    text = head + label + when + " (время Алматы)\n\nНажмите «Участвовать», чтобы попасть в розыгрыш."
    ents = list(entities_from_store(c.entities) or [])
    ents.append(MessageEntity(type="bold", offset=u16(head + label), length=u16(when)))
    return Rich(text, ents)


def join_kb(cid: int):
    return kb([btn("🎉 Участвовать", Cn(a="join", i=cid))])


def name_of(u: User | None, uid: int) -> str:
    if u is None:
        return f"id{uid}"
    return u.full_name or (f"@{u.username}" if u.username else f"id{uid}")


def mention(uid: int, name: str) -> str:
    """Кликабельное имя: открывает профиль пользователя."""
    return f'<a href="tg://user?id={uid}">{h(name)}</a>'


def result_html(c: Contest, winner_name: str) -> str:
    """Текст поздравления с кликабельным именем победителя."""
    return (c.result or DEFAULT_RESULT).replace("{winner}", mention(c.winner_id, winner_name))


async def _send(bot: Bot, uid: int, rich: Rich, markup=None) -> str:
    """ok / blocked / fail. Если Telegram не принял премиум эмодзи, шлём без них."""
    ents = rich.entities or []
    for variant in (ents, [e for e in ents if e.type != "custom_emoji"]):
        try:
            await bot.send_message(uid, rich.text, entities=variant or None, parse_mode=None, reply_markup=markup)
            return "ok"
        except TelegramForbiddenError:
            return "blocked"
        except TelegramRetryAfter:
            raise
        except TelegramBadRequest as e:
            log.info("contest send to %s failed: %s", uid, e)
    return "fail"


async def mailing(bot: Bot, sm, cid: int, text: Rich, admin_id: int) -> None:
    sent = blocked = failed = 0
    last_id = 0
    try:
        while True:
            async with sm() as session:
                ids = (await session.execute(
                    select(User.id).where(User.is_blocked.is_(False), User.id > last_id)
                    .order_by(User.id).limit(500)
                )).scalars().all()
            if not ids:
                break
            dead = []
            for uid in ids:
                last_id = uid
                try:
                    res = await _send(bot, uid, text, join_kb(cid))
                except TelegramRetryAfter as e:
                    await asyncio.sleep(e.retry_after + 1)
                    res = "fail"
                if res == "ok":
                    sent += 1
                elif res == "blocked":
                    blocked += 1
                    dead.append(uid)
                else:
                    failed += 1
                await asyncio.sleep(0.05)
            if dead:
                async with sm() as session:
                    await session.execute(update(User).where(User.id.in_(dead)).values(is_blocked=True))
                    await session.commit()
    except Exception:
        log.exception("contest mailing crashed")
    try:
        await bot.send_message(
            admin_id,
            f"✅ Конкурс разослан клиентам\n\nДоставлено: <b>{sent}</b>\nЗаблокировали бота: <b>{blocked}</b>\n"
            f"Ошибок: <b>{failed}</b>\n\nНе забудьте опубликовать пост в канале и закрепить его.",
        )
    except (TelegramBadRequest, TelegramForbiddenError):
        pass


def start_mailing(bot: Bot, sm, cid: int, text: Rich, admin_id: int) -> None:
    task = asyncio.create_task(mailing(bot, sm, cid, text, admin_id))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


async def congratulate(bot: Bot, uid: int) -> None:
    try:
        await bot.send_message(uid, "🎉 Поздравляем, вы выиграли в конкурсе! "
                                    "Свяжитесь по контактам из условий конкурса, чтобы получить приз.")
    except (TelegramBadRequest, TelegramForbiddenError):
        pass


async def pick_other(session: AsyncSession, c: Contest) -> int | None:
    """Новый победитель из участников, по возможности не тот же самый."""
    uids = (await session.execute(
        select(ContestEntry.user_id).where(ContestEntry.contest_id == c.id))).scalars().all()
    others = [u for u in uids if u != c.winner_id] or uids
    return random.choice(others) if others else None


async def tick(bot: Bot, sm) -> None:
    """Раз в проход планировщика: подводит итоги конкурсов, у которых вышло время."""
    notes = []
    async with sm() as session:
        due = (await session.execute(
            select(Contest).where(Contest.status == "active", Contest.ends_at <= utcnow())
        )).scalars().all()
        for c in due:
            uids = (await session.execute(
                select(ContestEntry.user_id).where(ContestEntry.contest_id == c.id))).scalars().all()
            winner = random.choice(uids) if uids else None
            c.status = "finished"
            c.winner_id = winner
            if winner is None:
                notes.append((None, 0, "", ""))
                continue
            name = name_of(await session.get(User, winner), winner)
            notes.append((winner, len(uids), name, result_html(c, name)))
        await session.commit()
    for winner, count, name, post in notes:
        if winner is None:
            await notify_admins(bot, "🎁 Конкурс завершён: участников не было.", None)
            continue
        await notify_admins(bot, f"🏆 <b>Конкурс завершён</b>\nУчастников: <b>{count}</b>\n\n"
                                 f"Победитель: {mention(winner, name)}", None)
        await notify_admins(bot, "Текст поздравления (скопируйте и опубликуйте в канале):\n\n" + post, None)
        await congratulate(bot, winner)
