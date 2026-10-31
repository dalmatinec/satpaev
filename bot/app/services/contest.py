"""Конкурс: пост с кнопкой «Участвовать», рассылка клиентам, итоги по таймеру, тексты для канала."""

import asyncio
import logging
import random
import re
from datetime import datetime

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from aiogram.types import MessageEntity
from contextlib import suppress

from sqlalchemy import func, select, update
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
DEFAULT_LIST = "👥 Участники конкурса ({count}):"
DEFAULT_BTN = "🎉 Участвовать"
DEFAULT_DM = "🎉 Поздравляем, вы выиграли в конкурсе! Свяжитесь по контактам из условий конкурса, чтобы получить приз."


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


MAX_CHANNELS = 5
MEMBER = {"member", "administrator", "creator"}


def parse_channel(raw: str) -> tuple[str, str] | None:
    """@channel, https://t.me/channel или «-100id https://t.me/+ссылка» для приватного."""
    raw = (raw or "").strip()
    m = re.match(r"^(-100\d+)\s+(https://t\.me/\S+)$", raw)
    if m:
        return m.group(1), m.group(2)
    m = re.match(r"^(?:https?://)?(?:t\.me/|@)([A-Za-z][A-Za-z0-9_]{3,31})/?$", raw)
    if m:
        return "@" + m.group(1), f"https://t.me/{m.group(1)}"
    return None


async def missing_subs(bot: Bot, channels: list[dict] | None, user_id: int) -> list[dict]:
    """Каналы из условий, на которые пользователь не подписан. Если бот не может проверить канал, не блокируем."""
    missing = []
    for ch in channels or []:
        try:
            member = await bot.get_chat_member(ch["chat"], user_id)
        except (TelegramBadRequest, TelegramForbiddenError) as e:
            log.warning("contest: не могу проверить подписку на %s: %s", ch.get("chat"), e)
            continue
        status = getattr(member, "status", "")
        if status == "restricted" and getattr(member, "is_member", False):
            continue
        if status not in MEMBER:
            missing.append(ch)
    return missing


def conditions_kb(cid: int, missing: list[dict]):
    rows = [[btn(f"📢 {ch.get('title') or ch['chat']}", url=ch["url"])] for ch in missing if ch.get("url")]
    rows.append([btn("✅ Проверить", Cn(a="check", i=cid))])
    return kb(*rows)


async def deep_link(bot: Bot, cid: int) -> str:
    me = await bot.me()
    return f"https://t.me/{me.username}?start=ct{cid}"


async def join_kb(bot: Bot, cid: int, label: str | None = None, count: int = 0):
    """Кнопка-ссылка: при пересылке в канал Telegram сохраняет только такие кнопки. В скобках — участники."""
    text = (label or DEFAULT_BTN) + (f" ({count})" if count else "")
    return kb([btn(text, url=await deep_link(bot, cid))])


async def finished_kb(bot: Bot, cid: int, count: int):
    return kb([btn(f"🏁 Конкурс завершён · участников: {count}", url=await deep_link(bot, cid))])


async def count_entries(session: AsyncSession, cid: int) -> int:
    return await session.scalar(select(func.count(ContestEntry.id)).where(ContestEntry.contest_id == cid)) or 0


def name_of(u: User | None, uid: int) -> str:
    if u is None:
        return f"id{uid}"
    return u.full_name or (f"@{u.username}" if u.username else f"id{uid}")


def mention(uid: int, name: str) -> str:
    """Кликабельное имя: открывает профиль пользователя."""
    return f'<a href="tg://user?id={uid}">{h(name)}</a>'


async def participants(session: AsyncSession, cid: int) -> list[tuple[int, str]]:
    uids = (await session.execute(
        select(ContestEntry.user_id).where(ContestEntry.contest_id == cid).order_by(ContestEntry.id))).scalars().all()
    if not uids:
        return []
    users = {u.id: u for u in (await session.execute(select(User).where(User.id.in_(uids)))).scalars().all()}
    return [(uid, name_of(users.get(uid), uid)) for uid in uids]


def result_html(c: Contest, winner_name: str) -> str:
    """Текст поздравления с кликабельным именем победителя."""
    return (c.result or DEFAULT_RESULT).replace("{winner}", mention(c.winner_id, winner_name))


def list_texts(c: Contest, rows: list[tuple[int, str]]) -> list[str]:
    """Список участников для канала, порциями по лимиту Telegram."""
    head = (c.list_tpl or DEFAULT_LIST).replace("{count}", str(len(rows)))
    chunks, cur = [], head
    for i, (uid, name) in enumerate(rows, 1):
        line = f"{i}. {mention(uid, name)}"
        if len(cur) + len(line) + 1 > 3800:
            chunks.append(cur)
            cur = line
        else:
            cur += "\n" + line
    chunks.append(cur)
    return chunks


async def send_rich(bot: Bot, chat, rich: Rich, markup=None):
    """(ok / blocked / fail, сообщение). Если Telegram не принял премиум эмодзи, шлём без них."""
    ents = rich.entities or []
    for variant in (ents, [e for e in ents if e.type != "custom_emoji"]):
        try:
            m = await bot.send_message(chat, rich.text, entities=variant or None, parse_mode=None, reply_markup=markup)
            return "ok", m
        except TelegramForbiddenError:
            return "blocked", None
        except TelegramRetryAfter:
            raise
        except TelegramBadRequest as e:
            log.info("contest send to %s failed: %s", chat, e)
    return "fail", None


async def _send(bot: Bot, uid, rich: Rich, markup=None) -> str:
    return (await send_rich(bot, uid, rich, markup))[0]


async def _set_button(bot: Bot, chat: str, msg_id: int, markup) -> None:
    with suppress(TelegramBadRequest, TelegramForbiddenError):
        await bot.edit_message_reply_markup(chat_id=chat, message_id=msg_id, reply_markup=markup)


async def mailing(bot: Bot, sm, cid: int, text: Rich, admin_id: int, label: str | None = None) -> None:
    sent = blocked = failed = 0
    last_id = 0
    markup = await join_kb(bot, cid, label)
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
                    res = await _send(bot, uid, text, markup)
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
        async with sm() as session:
            await session.execute(update(Contest).where(Contest.id == cid).values(
                mail_sent=sent, mail_blocked=blocked, mail_failed=failed))
            await session.commit()
    except Exception:
        log.exception("contest mailing stats")
    try:
        await bot.send_message(
            admin_id,
            f"✅ Конкурс разослан клиентам\n\nДоставлено: <b>{sent}</b>\nЗаблокировали бота: <b>{blocked}</b>\n"
            f"Ошибок: <b>{failed}</b>\n\nНе забудьте опубликовать пост в канале и закрепить его. "
            f"Ссылка для участия из канала:\n<code>{await deep_link(bot, cid)}</code>",
        )
    except (TelegramBadRequest, TelegramForbiddenError):
        pass


def start_mailing(bot: Bot, sm, cid: int, text: Rich, admin_id: int, label: str | None = None) -> None:
    task = asyncio.create_task(mailing(bot, sm, cid, text, admin_id, label))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


async def congratulate(bot: Bot, uid: int, text: str) -> None:
    try:
        await bot.send_message(uid, text)
    except (TelegramBadRequest, TelegramForbiddenError):
        pass


async def pick_other(session: AsyncSession, c: Contest) -> int | None:
    """Новый победитель из участников, по возможности не тот же самый."""
    uids = [uid for uid, _ in await participants(session, c.id)]
    others = [u for u in uids if u != c.winner_id] or uids
    return random.choice(others) if others else None


async def tick(bot: Bot, sm) -> None:
    """Раз в проход планировщика: подводит итоги конкурсов, у которых вышло время."""
    notes = []
    async with sm() as session:
        # счётчик на кнопке поста в канале: обновляем, если число участников изменилось
        live = (await session.execute(
            select(Contest).where(Contest.status == "active", Contest.pub_msg.is_not(None)))).scalars().all()
        for c in live:
            count = await count_entries(session, c.id)
            if count != c.pub_count:
                await _set_button(bot, c.pub_chat, c.pub_msg, await join_kb(bot, c.id, c.btn_text, count))
                c.pub_count = count
        await session.commit()
        due = (await session.execute(
            select(Contest).where(Contest.status == "active", Contest.ends_at <= utcnow())
        )).scalars().all()
        for c in due:
            rows = await participants(session, c.id)
            winner = random.choice(rows)[0] if rows else None
            c.status = "finished"
            c.winner_id = winner
            if c.pub_msg:
                await _set_button(bot, c.pub_chat, c.pub_msg, await finished_kb(bot, c.id, len(rows)))
            if winner is None:
                notes.append({"winner": None})
                continue
            name = next(n for uid, n in rows if uid == winner)
            notes.append({"winner": winner, "count": len(rows), "name": name,
                          "result": result_html(c, name), "lists": list_texts(c, rows),
                          "dm": c.dm_tpl or DEFAULT_DM})
        await session.commit()
    for n in notes:
        if n["winner"] is None:
            await notify_admins(bot, "🎁 Конкурс завершён: участников не было.", None)
            continue
        await notify_admins(bot, f"🏆 <b>Конкурс завершён</b>\nУчастников: <b>{n['count']}</b>\n\n"
                                 f"Победитель: {mention(n['winner'], n['name'])}", None)
        await notify_admins(bot, "Текст поздравления (скопируйте и опубликуйте в канале):\n\n" + n["result"], None)
        await notify_admins(bot, "Список участников для канала:", None)
        for chunk in n["lists"]:
            await notify_admins(bot, chunk, None)
        await congratulate(bot, n["winner"], n["dm"])
