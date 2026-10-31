"""Конкурс: пост с кнопкой «Участвовать», рассылка клиентам, итоги по таймеру."""

import asyncio
import logging
import random
import re
from datetime import datetime

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from sqlalchemy import select, update

from ..cb import Cn
from ..config import config
from ..db.models import Contest, ContestEntry, User
from ..ui import btn, kb
from ..utils import h, utcnow
from .orders import notify_admins

log = logging.getLogger(__name__)
_tasks: set = set()
DATE_RE = re.compile(r"^\s*(\d{1,2})\.(\d{1,2})\s+(\d{1,2}):(\d{2})\s*$")


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


def body(c: Contest) -> str:
    return (f"{c.text}\n\n⏳ Итоги: <b>{deadline_text(c)}</b> (время Алматы)\n\n"
            "Нажмите «Участвовать», чтобы попасть в розыгрыш.")


def join_kb(cid: int):
    return kb([btn("🎉 Участвовать", Cn(a="join", i=cid))])


def name_of(u: User | None, uid: int) -> str:
    if u is None:
        return f"id{uid}"
    return u.full_name or (f"@{u.username}" if u.username else f"id{uid}")


def mention(uid: int, name: str) -> str:
    """Кликабельное имя: открывает профиль пользователя."""
    return f'<a href="tg://user?id={uid}">{h(name)}</a>'


async def mailing(bot: Bot, sm, cid: int, text: str, admin_id: int) -> None:
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
                    await bot.send_message(uid, text, reply_markup=join_kb(cid))
                    sent += 1
                except TelegramRetryAfter as e:
                    await asyncio.sleep(e.retry_after + 1)
                    failed += 1
                except TelegramForbiddenError:
                    blocked += 1
                    dead.append(uid)
                except TelegramBadRequest:
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


def start_mailing(bot: Bot, sm, cid: int, text: str, admin_id: int) -> None:
    task = asyncio.create_task(mailing(bot, sm, cid, text, admin_id))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


async def tick(bot: Bot, sm) -> None:
    """Раз в проход планировщика: подводит итоги конкурсов, у которых вышло время."""
    results = []
    async with sm() as session:
        due = (await session.execute(
            select(Contest).where(Contest.status == "active", Contest.ends_at <= utcnow())
        )).scalars().all()
        for c in due:
            uids = (await session.execute(
                select(ContestEntry.user_id).where(ContestEntry.contest_id == c.id)
            )).scalars().all()
            winner = random.choice(uids) if uids else None
            name = name_of(await session.get(User, winner), winner) if winner else ""
            c.status = "finished"
            c.winner_id = winner
            results.append((len(uids), winner, name))
        await session.commit()
    for count, winner, name in results:
        if winner is None:
            await notify_admins(bot, "🎁 Конкурс завершён: участников не было.", None)
            continue
        link = mention(winner, name)
        await notify_admins(bot, f"🏆 <b>Конкурс завершён</b>\nУчастников: <b>{count}</b>\n\nПобедитель: {link}", None)
        await notify_admins(bot, "Текст для поста (скопируйте и опубликуйте в канале):\n\n"
                                 f"🏆 Итоги конкурса! Победитель: {link}. Поздравляем!", None)
        try:
            await bot.send_message(winner, "🎉 Поздравляем, вы выиграли в конкурсе! "
                                           "Свяжитесь по контактам из условий конкурса, чтобы получить приз.")
        except (TelegramBadRequest, TelegramForbiddenError):
            pass
