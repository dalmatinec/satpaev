"""Админка: конкурс. Тексты (все редактируются), предпросмотр, рассылка, участники, итоги, список для канала."""

from datetime import timedelta

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...cb import Adm
from ...config import config
from ...db.models import Contest, ContestEntry, User
from ...services import contest as svc
from ...ui import answer, btn, kb, say, show
from ...utils import entities_to_store, h, utcnow
from .common import Ctx, ask, op, screen

router = Router(name="admin_contest")

FIELD_PROMPTS = {
    "text": "✏️ <b>Текст поста</b>\n\nПришлите новый текст. Премиум эмодзи и форматирование сохранятся.",
    "btn_text": "✏️ <b>Надпись на кнопке</b> (до 40 символов). Число участников бот добавит в скобках сам. "
                "Отправьте <code>-</code>, чтобы вернуть стандартную.",
    "result": "✏️ <b>Текст поздравления</b> (итоги для канала). Вместо имени победителя поставьте "
              "<code>{winner}</code>. Отправьте <code>-</code>, чтобы вернуть стандартный.",
    "list_tpl": "✏️ <b>Шапка списка участников</b>. Вместо количества поставьте <code>{count}</code>. "
                "Отправьте <code>-</code>, чтобы вернуть стандартную.",
    "dm_tpl": "✏️ <b>Личное сообщение победителю</b>. Отправьте <code>-</code>, чтобы вернуть стандартное.",
}
FIELD_NAMES = {"text": "Текст поста", "btn_text": "Надпись на кнопке", "result": "Поздравление (итоги)",
               "list_tpl": "Шапка списка участников", "dm_tpl": "Личка победителю"}


async def _active(session: AsyncSession):
    return await session.scalar(select(Contest).where(Contest.status == "active").limit(1))


async def _count(session: AsyncSession, cid: int, since=None) -> int:
    q = select(func.count(ContestEntry.id)).where(ContestEntry.contest_id == cid)
    if since is not None:
        q = q.where(ContestEntry.created_at >= since)
    return await session.scalar(q) or 0


def _preview_kb(cid: int):
    return kb([btn("🚀 Запустить рассылку", Adm(s="ct", a="start", i=cid))],
              [btn("✏️ Тексты", Adm(s="ct", a="texts", i=cid))],
              [btn("📢 Каналы-условия", Adm(s="ct", a="chans", i=cid))],
              [btn("◀️ Отмена", Adm(s="ct", a="drop", i=cid))])


async def _stats(session: AsyncSession, c: Contest) -> str:
    now = utcnow()
    midnight = now.astimezone(config.tz).replace(hour=0, minute=0, second=0, microsecond=0)
    total = await _count(session, c.id)
    hour = await _count(session, c.id, now - timedelta(hours=1))
    today = await _count(session, c.id, midnight)
    lines = [f"👥 Участников: <b>{total}</b> (за час: +{hour}, сегодня: +{today})",
             f"🚫 Нажали без подписки: <b>{c.clicks_missing or 0}</b>"]
    if c.mail_sent or c.mail_blocked or c.mail_failed:
        lines.append(f"📨 Рассылка: доставлено <b>{c.mail_sent}</b> · заблокировали {c.mail_blocked} · "
                     f"ошибок {c.mail_failed}")
    lines.append("📢 В канале: " + ("опубликован, счётчик на кнопке обновляется" if c.pub_msg else "не опубликован"))
    lines.append(f"📋 Каналов в условиях: <b>{len(c.channels or [])}</b>")
    return "\n".join(lines)


@screen("ct")
async def view(target, session: AsyncSession, cbd: Adm) -> None:
    active = await _active(session)
    if active:
        link = await svc.deep_link(target.bot, active.id)
        text = (f"🎁 <b>Конкурс идёт</b>\n\n{await _stats(session, active)}\n"
                f"⏳ Итоги: <b>{svc.deadline_text(active)}</b>, бот выберет победителя сам.\n\n"
                f"Ссылка на участие:\n<code>{link}</code>")
        i = active.id
        rows = [[btn("📢 Опубликовать в канал", Adm(s="ct", a="pub", i=i))],
                [btn("👥 Участники", Adm(s="ct", a="list", i=i)), btn("✏️ Тексты", Adm(s="ct", a="texts", i=i))],
                [btn("📢 Каналы-условия", Adm(s="ct", a="chans", i=i))],
                [btn("🎲 Подвести итоги сейчас", Adm(s="ct", a="end", i=i))],
                [btn("⏹ Отменить конкурс", Adm(s="ct", a="cancel", i=i))]]
    else:
        rows = []
        last = await session.scalar(
            select(Contest).where(Contest.status == "finished").order_by(Contest.id.desc()).limit(1))
        if last is None:
            text = "🎁 <b>Конкурс</b>\n\nКонкурсов ещё не было."
        else:
            i = last.id
            text = (f"🎁 <b>Последний конкурс</b> · итоги {svc.deadline_text(last)}\n\n"
                    f"{await _stats(session, last)}\n")
            if last.winner_id:
                name = svc.name_of(await session.get(User, last.winner_id), last.winner_id)
                text += (f"\n🏆 Победитель: {svc.mention(last.winner_id, name)}\n\n<b>Текст итогов:</b>\n"
                         f"{svc.result_html(last, name)}")
                rows.append([btn("📢 Итоги в канал", Adm(s="ct", a="pubres", i=i)),
                             btn("🎲 Другой победитель", Adm(s="ct", a="reroll", i=i))])
            else:
                text += "\nУчастников не было."
            rows.append([btn("📢 Список участников в канал", Adm(s="ct", a="publist", i=i))])
            rows.append([btn("👥 Участники", Adm(s="ct", a="list", i=i)),
                         btn("📋 Список мне", Adm(s="ct", a="sendlist", i=i))])
            rows.append([btn("✏️ Тексты", Adm(s="ct", a="texts", i=i))])
    rows.append([btn("✍️ Новый конкурс", Adm(s="ct", a="new"))])
    rows.append([btn("◀️ Админка", Adm(s="menu"))])
    await show(target, text, kb(*rows))


async def _texts_screen(target, session: AsyncSession, cid: int) -> None:
    c = await session.get(Contest, cid)
    if c is None:
        await view(target, session, Adm(s="ct"))
        return
    current = {
        "text": (c.text or "")[:120] + ("…" if len(c.text or "") > 120 else ""),
        "btn_text": c.btn_text or svc.DEFAULT_BTN,
        "result": c.result or svc.DEFAULT_RESULT,
        "list_tpl": c.list_tpl or svc.DEFAULT_LIST,
        "dm_tpl": c.dm_tpl or svc.DEFAULT_DM,
    }
    fields = list(FIELD_NAMES) if c.status == "draft" else [f for f in FIELD_NAMES if f != "text"]
    text = "✏️ <b>Тексты конкурса</b>\n\n" + "\n\n".join(
        f"<b>{FIELD_NAMES[f]}:</b>\n{h(current[f])}" for f in fields)
    if c.status != "draft":
        text += "\n\n<i>Текст поста уже разослан, его можно поправить прямо в канале.</i>"
    rows = [[btn(f"✏️ {FIELD_NAMES[f]}", Adm(s="ct", a="edit", i=cid, v=f))] for f in fields]
    back = Adm(s="ct", a="prev", i=cid) if c.status == "draft" else Adm(s="ct")
    rows.append([btn("◀️ Назад", back)])
    await show(target, text, kb(*rows))


async def _to_channel(cb: CallbackQuery, texts: list[str]) -> None:
    if not config.channel_id:
        await answer(cb, "Канал не задан: укажите CHANNEL_ID в .env", alert=True)
        return
    try:
        for t in texts:
            await cb.bot.send_message(config.channel_id, t)
    except TelegramForbiddenError:
        await answer(cb, "⚠️ Бот не админ канала или нет права публиковать", alert=True)
        return
    except TelegramBadRequest as e:
        await answer(cb, f"⚠️ Не удалось: {e}"[:190], alert=True)
        return
    await answer(cb, "✅ Опубликовано в канал", alert=True)


@router.callback_query(Adm.filter(F.s == "ct"))
async def on_ct(cb: CallbackQuery, callback_data: Adm, session: AsyncSession, state: FSMContext, sm) -> None:
    a, cid, field = callback_data.a, callback_data.i, callback_data.v
    if a == "new":
        if await _active(session):
            await answer(cb, "Сначала завершите или отмените текущий конкурс", alert=True)
            return
        await ask(cb, state, "ct_text",
                  "🎁 <b>Новый конкурс</b>\n\nПришлите текст: призы, условия и куда писать за призом "
                  "(например @set_fact). Премиум эмодзи и форматирование сохранятся.", Adm(s="ct"))
        return
    if a == "texts":
        await _texts_screen(cb, session, cid)
        return
    if a == "edit" and field in FIELD_PROMPTS:
        await ask(cb, state, "ct_edit", FIELD_PROMPTS[field], Adm(s="ct", a="texts", i=cid), cid=cid, field=field)
        return
    if a == "list":
        await _show_list(cb, session, cid)
        return
    if a == "prev":
        c = await session.get(Contest, cid)
        if c is not None and c.status == "draft":
            await show(cb, svc.body(c), _preview_kb(cid))
            return
    if a == "chans":
        await _chans_screen(cb, session, cid)
        return
    if a == "pub":
        c = await session.get(Contest, cid)
        if c is None or c.status != "active":
            await answer(cb, "Публиковать можно только идущий конкурс", alert=True)
            return
        if not config.channel_id:
            await answer(cb, "Канал не задан: укажите CHANNEL_ID в .env", alert=True)
            return
        count = await _count(session, cid)
        res, m = await svc.send_rich(cb.bot, config.channel_id, svc.body(c),
                                     await svc.join_kb(cb.bot, cid, c.btn_text, count))
        if res == "ok" and m is not None:
            c.pub_chat, c.pub_msg, c.pub_count = str(m.chat.id), m.message_id, count
            await session.commit()
        msg = {"ok": "✅ Опубликовано в канал. На кнопке будет счётчик участников. Премиум эмодзи можно "
                     "поправить в канале.",
               "blocked": "⚠️ Бот не админ канала или нет права публиковать"}.get(res, "⚠️ Не удалось опубликовать, см. логи")
        await answer(cb, msg, alert=True)
        await view(cb, session, callback_data)
        return
    if a == "pubres":
        c = await session.get(Contest, cid)
        if c is None or not c.winner_id:
            await answer(cb, "Победителя нет", alert=True)
            return
        name = svc.name_of(await session.get(User, c.winner_id), c.winner_id)
        await _to_channel(cb, [svc.result_html(c, name)])
        return
    if a == "publist":
        c = await session.get(Contest, cid)
        if c is None:
            return
        await _to_channel(cb, svc.list_texts(c, await svc.participants(session, cid)))
        return
    if a == "chadd":
        c = await session.get(Contest, cid)
        if c is not None and len(c.channels or []) >= svc.MAX_CHANNELS:
            await answer(cb, f"Максимум {svc.MAX_CHANNELS} каналов", alert=True)
            return
        await ask(cb, state, "ct_chadd",
                  "➕ Пришлите канал:\n• публичный: <code>@channel</code> или <code>https://t.me/channel</code>\n"
                  "• приватный: <code>-100id https://t.me/+ссылка</code>\n\n"
                  "Бот должен быть админом в канале, иначе подписку проверить нельзя.",
                  Adm(s="ct", a="chans", i=cid), cid=cid)
        return
    if a == "chdel":
        c = await session.get(Contest, cid)
        if c is not None:
            chans = list(c.channels or [])
            idx = int(field) if field.isdigit() else -1
            if 0 <= idx < len(chans):
                chans.pop(idx)
                c.channels = chans or None
                await session.commit()
        await _chans_screen(cb, session, cid)
        return
    if a == "sendlist":
        c = await session.get(Contest, cid)
        if c is None:
            return
        rows = await svc.participants(session, cid)
        for chunk in svc.list_texts(c, rows):
            await cb.bot.send_message(cb.from_user.id, chunk)
        await answer(cb, "Список отправил в чат")
        return
    if a == "end":
        c = await session.get(Contest, cid)
        if c and c.status == "active":
            c.ends_at = utcnow()  # следующий проход планировщика (до минуты) подведёт итоги
            await session.commit()
            await answer(cb, "Итоги подведу в течение минуты")
    elif a == "cancel":
        c = await session.get(Contest, cid)
        if c and c.status == "active":
            c.status = "cancelled"
            await session.commit()
    elif a == "drop":
        c = await session.get(Contest, cid)
        if c and c.status == "draft":
            c.status = "cancelled"
            await session.commit()
    elif a == "reroll":
        c = await session.get(Contest, cid)
        if not c or c.status != "finished" or not c.winner_id:
            await answer(cb, "Некого перевыбирать", alert=True)
            return
        winner = await svc.pick_other(session, c)
        if winner is None:
            await answer(cb, "Участников нет", alert=True)
            return
        c.winner_id = winner
        dm = c.dm_tpl or svc.DEFAULT_DM
        await session.commit()
        await svc.congratulate(cb.bot, winner, dm)
        await answer(cb, "Победитель выбран заново")
    elif a == "start":
        c = await session.get(Contest, cid)
        if not c or c.status != "draft":
            await answer(cb, "Этот конкурс уже запущен или отменён", alert=True)
            return
        if await _active(session):
            await answer(cb, "Уже идёт другой конкурс", alert=True)
            return
        text, label = svc.body(c), c.btn_text
        c.status = "active"
        await session.commit()
        svc.start_mailing(cb.bot, sm, cid, text, cb.from_user.id, label)
        await answer(cb, "Рассылка запущена")
    await view(cb, session, callback_data)


async def _chans_screen(target, session: AsyncSession, cid: int) -> None:
    c = await session.get(Contest, cid)
    if c is None:
        await view(target, session, Adm(s="ct"))
        return
    chans = c.channels or []
    lines = [f"{i}. {h(ch.get('title') or ch['chat'])} ({h(ch['chat'])})" for i, ch in enumerate(chans, 1)]
    text = ("📢 <b>Каналы-условия</b>\n\nЧтобы участвовать, нужно подписаться на все эти каналы. "
            f"Бот проверяет подписку при нажатии «Участвовать». До {svc.MAX_CHANNELS} каналов.\n\n"
            + ("\n".join(lines) or "Каналов нет: участвовать может любой, кто запустил бота."))
    rows = [[btn(f"🗑 {(ch.get('title') or ch['chat'])[:40]}", Adm(s="ct", a="chdel", i=cid, v=str(i)))]
            for i, ch in enumerate(chans)]
    if len(chans) < svc.MAX_CHANNELS:
        rows.append([btn("➕ Добавить канал", Adm(s="ct", a="chadd", i=cid))])
    back = Adm(s="ct", a="prev", i=cid) if c.status == "draft" else Adm(s="ct")
    rows.append([btn("◀️ Назад", back)])
    await show(target, text, kb(*rows))


async def _show_list(cb: CallbackQuery, session: AsyncSession, cid: int) -> None:
    c = await session.get(Contest, cid)
    if c is None:
        return
    chunks = svc.list_texts(c, await svc.participants(session, cid))
    await show(cb, chunks[0] + "\n\nПолный список: «📋 Список мне» или «📢 Список участников в канал».",
               kb([btn("◀️ Назад", Adm(s="ct"))]))


@op("ct_text")
async def op_ct_text(ctx: Ctx) -> None:
    msg = ctx.message
    text = (msg.text if msg is not None and msg.text else (ctx.text or "")).strip()
    if not text or len(text) > 3000:
        await say(ctx.target, "Нужен текст до 3000 символов. Пришлите ещё раз:")
        return
    entities = entities_to_store(msg.entities) if msg is not None and msg.text else []
    await ask(ctx.target, ctx.state, "ct_time",
              "⏳ Когда подводить итоги?\n\nФормат: <code>ДД.ММ ЧЧ:ММ</code> по времени Алматы, например "
              "<code>05.11 20:00</code>", Adm(s="ct"), text=text, entities=entities)


@op("ct_time")
async def op_ct_time(ctx: Ctx) -> None:
    deadline = svc.parse_deadline(ctx.text)
    if deadline is None:
        await say(ctx.target, "Не понял время, или оно уже прошло. Формат: <code>ДД.ММ ЧЧ:ММ</code>, например "
                              "<code>05.11 20:00</code>")
        return
    c = Contest(text=ctx.data["text"], entities=ctx.data.get("entities") or None, ends_at=deadline, status="draft")
    ctx.session.add(c)
    await ctx.session.flush()
    cid = c.id
    preview = svc.body(c)
    await ctx.session.commit()
    await ctx.state.clear()
    await show(ctx.target, preview, _preview_kb(cid))


@op("ct_edit")
async def op_ct_edit(ctx: Ctx) -> None:
    field, cid = ctx.data["field"], ctx.data["cid"]
    msg = ctx.message
    c = await ctx.session.get(Contest, cid)
    if c is None:
        await ctx.state.clear()
        await view(ctx.target, ctx.session, Adm(s="ct"))
        return
    if field == "text":
        plain = (msg.text if msg is not None and msg.text else (ctx.text or "")).strip()
        if not plain or len(plain) > 3000:
            await say(ctx.target, "Нужен текст до 3000 символов. Пришлите ещё раз:")
            return
        c.text = plain
        c.entities = entities_to_store(msg.entities) if msg is not None and msg.text else []
    elif field == "btn_text":
        label = (ctx.text or "").strip()
        if not label or len(label) > 40:
            await say(ctx.target, "Нужна надпись до 40 символов. Пришлите ещё раз:")
            return
        c.btn_text = None if label == "-" else label
        c.pub_count = -1  # обновить кнопку в канале на следующем проходе
    else:
        html = (msg.html_text if msg is not None and msg.text else (ctx.text or "")).strip()
        if not html or len(html) > 1000:
            await say(ctx.target, "Нужен текст до 1000 символов. Пришлите ещё раз:")
            return
        setattr(c, field, None if html == "-" else html)
    draft = c.status == "draft"
    preview = svc.body(c) if draft else None
    await ctx.session.commit()
    await ctx.state.clear()
    if draft and field == "text":
        await show(ctx.target, preview, _preview_kb(cid))
    else:
        await _texts_screen(ctx.target, ctx.session, cid)



@op("ct_chadd")
async def op_ct_chadd(ctx: Ctx) -> None:
    parsed = svc.parse_channel(ctx.text or "")
    if parsed is None:
        await say(ctx.target, "Не понял. Пример: <code>@newssatbox</code>")
        return
    chat, url = parsed
    try:
        info = await ctx.bot.get_chat(chat)
        me = await ctx.bot.me()
        member = await ctx.bot.get_chat_member(chat, me.id)
    except (TelegramBadRequest, TelegramForbiddenError):
        await say(ctx.target, "Бот не видит этот канал. Добавьте бота в канал админом и пришлите ещё раз.")
        return
    if member.status not in ("administrator", "creator"):
        await say(ctx.target, "Бот не админ в этом канале, подписку проверить не получится. "
                              "Сделайте бота админом и пришлите ещё раз.")
        return
    cid = ctx.data["cid"]
    c = await ctx.session.get(Contest, cid)
    if c is not None:
        chans = [ch for ch in (c.channels or []) if ch["chat"] != chat]
        chans.append({"chat": chat, "url": url, "title": info.title or chat})
        c.channels = chans[: svc.MAX_CHANNELS]
        await ctx.session.commit()
    await ctx.state.clear()
    await _chans_screen(ctx.target, ctx.session, cid)
