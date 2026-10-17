"""Фоновые задачи: напоминания, ежедневный бэкап, уборка."""

import asyncio
import logging
import os
import time
from datetime import datetime, timedelta

from aiogram import Bot
from sqlalchemy import delete, or_, select

from ..cb import Adm
from ..config import config
from ..db.models import Post, Reminder, SupportLink
from ..ui import btn, kb
from ..utils import utcnow
from . import backup, settings
from .orders import notify_admins

log = logging.getLogger(__name__)


async def _reminders(bot: Bot, sm) -> None:
    async with sm() as session:
        rows = (await session.execute(
            select(Reminder).where(Reminder.sent.is_(False), Reminder.due_at <= utcnow()).order_by(Reminder.due_at).limit(20)
        )).scalars().all()
        for r in rows:
            r.sent = True
        await session.commit()
    for r in rows:
        markup = kb([btn("📂 Открыть заказ", Adm(s="ord", a="card", i=r.order_id))]) if r.order_id else None
        await notify_admins(bot, r.text, markup)


async def _daily_backup(bot: Bot, sm) -> None:
    now = datetime.now(config.tz)
    hhmm = str(settings.get("backup_time") or "04:00")
    try:
        hh, mm = (int(x) for x in hhmm.split(":"))
    except ValueError:
        hh, mm = 4, 0
    today = now.strftime("%Y-%m-%d")
    if settings.get("backup_last_day") == today:
        return
    if (now.hour, now.minute) < (hh, mm):
        return
    async with sm() as session:
        await settings.put(session, "backup_last_day", today)
        await session.commit()
    await backup.make_backup(bot, sm)


async def _cleanup(sm) -> None:
    month_ago = utcnow() - timedelta(days=30)
    async with sm() as session:
        await session.execute(delete(SupportLink).where(SupportLink.created_at < month_ago))
        await session.execute(delete(Reminder).where(Reminder.sent.is_(True), Reminder.due_at < month_ago))
        media = (await session.execute(
            select(Post.id, Post.media).where(
                Post.media != "",
                or_(Post.status == "sent", Post.created_at < utcnow() - timedelta(days=7)),
            )
        )).all()
        for post_id, path in media:
            try:
                os.remove(path)
            except OSError:
                pass
            await session.execute(Post.__table__.update().where(Post.id == post_id).values(media=""))
        await session.commit()


async def run(bot: Bot, sm) -> None:
    last_cleanup = 0.0
    while True:
        try:
            await _reminders(bot, sm)
            await _daily_backup(bot, sm)
            if time.monotonic() - last_cleanup > 3600:
                await _cleanup(sm)
                last_cleanup = time.monotonic()
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("scheduler tick failed")
        await asyncio.sleep(30)
