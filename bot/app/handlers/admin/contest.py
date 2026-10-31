"""Админка: конкурс. Тексты (все редактируются), предпросмотр, рассылка, участники, итоги, список для канала."""

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
    "result": "✏️ <b>Текст поздравления</b> для канала. Вместо имени победителя поставьте <code>{winner}</code>. "
              "Отправьте <code>-</code>, чтобы вернуть стандартный.",
    "list_tpl": "✏️ <b>Шапка списка участников</b>. Вместо количества поставьте <code>{count}</code>. "
                "Отправьте <code>-</code>, чтобы вернуть стандартную.",
    "dm_tpl": "✏️ <b>Личное сообщение победителю</b>. Отправьте <code>-</code>, чтобы вернуть стандартное.",
}


async def _active(session: AsyncSession):
    return await session.scalar(select(Contest).where(Contest.status == "active").limit(1))


async def _count(session: AsyncSession, cid: int) -> int:
    return await session.scalar(select(func.count(ContestEntry.id)).where(ContestEntry.contest_id == cid)) or 0


def _preview_kb(cid: int):
    return kb([btn("🚀 Запустить рассылку", Adm(s="ct", a="start", i=cid))],
              [btn("✏️ Изменить текст", Adm(s="ct", a="edit", i=cid, v="text"))],
              [btn("📢 Каналы-условия", Adm(s="ct", a="chans", i=cid))],
              [btn("◀️ Отмена", Adm(s="ct", a="drop", i=cid))])


@screen("ct")
async def view(target, session: AsyncSession, cbd: Adm) -> None:
    active = await _active(session)
    if active:
        count = await _count(session, active.id)
        link = await svc.deep_link(target.bot, active.id)
        text = (f"🎁 <b>Конкурс идёт</b>\n\nУчастников: <b>{count}</b>\n"
                f"Итоги: <b>{svc.deadline_text(active)}</b>, бот выберет победителя сам.\n"
                f"Каналов в условиях: <b>{len(active.channels or [])}</b>\n\n"
                f"Ссылка для поста в канале:\n<code>{link}</code>")
        rows = [[btn("📢 Опубликовать в канал", Adm(s="ct", a="pub", i=active.id))],
                [btn("👥 Участники", Adm(s="ct", a="list", i=active.id))],
                [btn("📢 Каналы-условия", Adm(s="ct", a="chans", i=active.id))],
                [btn("🎲 Подвести итоги сейчас", Adm(s="ct", a="end", i=active.id))],
                [btn("⏹ Отменить конкурс", Adm(s="ct", a="cancel", i=active.id))]]
    else:
        rows = []
        last = await session.scalar(
            select(Contest).where(Contest.status == "finished").order_by(Contest.id.desc()).limit(1))
        if last is None:
            text = "🎁 <b>Конкурс</b>\n\nКонкурсов ещё не было."
        else:
            count = await _count(session, last.id)
            text = (f"🎁 <b>Последний конкурс</b>\n\nИтоги: <b>{svc.deadline_text(last)}</b>\n"
                    f"Участников: <b>{count}</b>\n")
            if last.winner_id:
                name = svc.name_of(await session.get(User, last.winner_id), last.winner_id)
                text += (f"Победитель: {svc.mention(last.winner_id, name)}\n\n<b>Текст поздравления:</b>\n"
                         f"{svc.result_html(last, name)}")
                rows.append([btn("🎲 Выбрать другого", Adm(s="ct", a="reroll", i=last.id))])
            else:
                text += "\nУчастников не было."
            rows.append([btn("👥 Участники", Adm(s="ct", a="list", i=last.id))])
            rows.append([btn("📋 Прислать список для канала", Adm(s="ct", a="sendlist", i=last.id))])
            rows.append([btn("✏️ Текст поздравления", Adm(s="ct", a="edit", i=last.id, v="result"))])
            rows.append([btn("✏️ Шапка списка", Adm(s="ct", a="edit", i=last.id, v="list_tpl"))])
            rows.append([btn("✏️ Личка победителю", Adm(s="ct", a="edit", i=last.id, v="dm_tpl"))])
    rows.append([btn("✍️ Новый конкурс", Adm(s="ct", a="new"))])
    rows.append([btn("◀️ Админка", Adm(s="menu"))])
    await show(target, text, kb(*rows))


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
    if a == "edit" and field in FIELD_PROMPTS:
        await ask(cb, state, "ct_edit", FIELD_PROMPTS[field], Adm(s="ct"), cid=cid, field=field)
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
        res = await svc._send(cb.bot, config.channel_id, svc.body(c), await svc.join_kb(cb.bot, cid))
        msg = {"ok": "✅ Опубликовано в канал с кнопкой «Участвовать». Премиум эмодзи можно поправить в канале.",
               "blocked": "⚠️ Бот не админ канала или нет права публиковать"}.get(res, "⚠️ Не удалось опубликовать, см. логи")
        await answer(cb, msg, alert=True)
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
        text = svc.body(c)
        c.status = "active"
        await session.commit()
        svc.start_mailing(cb.bot, sm, cid, text, cb.from_user.id)
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
    await show(cb, chunks[0] + "\n\nПолный список для канала: кнопка «📋 Прислать список для канала».",
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
    if draft:
        await show(ctx.target, preview, _preview_kb(cid))
    else:
        await view(ctx.target, ctx.session, Adm(s="ct"))



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
