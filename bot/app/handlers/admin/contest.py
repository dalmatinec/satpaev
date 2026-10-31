"""Админка: конкурс. Текст и время, предпросмотр, рассылка, участники, итоги, текст поздравления."""

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...cb import Adm
from ...db.models import Contest, ContestEntry, User
from ...services import contest as svc
from ...utils import entities_to_store, utcnow
from ...ui import answer, btn, kb, say, show
from .common import Ctx, ask, op, screen

router = Router(name="admin_contest")


async def _active(session: AsyncSession):
    return await session.scalar(select(Contest).where(Contest.status == "active").limit(1))


async def _count(session: AsyncSession, cid: int) -> int:
    return await session.scalar(select(func.count(ContestEntry.id)).where(ContestEntry.contest_id == cid)) or 0


async def _winner_mention(session: AsyncSession, c: Contest) -> tuple[str, str]:
    name = svc.name_of(await session.get(User, c.winner_id), c.winner_id)
    return name, svc.mention(c.winner_id, name)


@screen("ct")
async def view(target, session: AsyncSession, cbd: Adm) -> None:
    active = await _active(session)
    if active:
        count = await _count(session, active.id)
        text = (f"🎁 <b>Конкурс идёт</b>\n\nУчастников: <b>{count}</b>\n"
                f"Итоги: <b>{svc.deadline_text(active)}</b>, бот выберет победителя сам.")
        rows = [[btn("👥 Участники", Adm(s="ct", a="list", i=active.id))],
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
                name, link = await _winner_mention(session, last)
                text += (f"Победитель: {link}\n\n<b>Текст поздравления:</b>\n"
                         f"{svc.result_html(last, name)}")
                rows.append([btn("🎲 Выбрать другого", Adm(s="ct", a="reroll", i=last.id))])
            else:
                text += "\nУчастников не было."
            rows.append([btn("👥 Участники", Adm(s="ct", a="list", i=last.id))])
            rows.append([btn("✏️ Текст поздравления", Adm(s="ct", a="res", i=last.id))])
    rows.append([btn("✍️ Новый конкурс", Adm(s="ct", a="new"))])
    rows.append([btn("◀️ Админка", Adm(s="menu"))])
    await show(target, text, kb(*rows))


@router.callback_query(Adm.filter(F.s == "ct"))
async def on_ct(cb: CallbackQuery, callback_data: Adm, session: AsyncSession, state: FSMContext, sm) -> None:
    a, cid = callback_data.a, callback_data.i
    if a == "new":
        if await _active(session):
            await answer(cb, "Сначала завершите или отмените текущий конкурс", alert=True)
            return
        await ask(cb, state, "ct_text",
                  "🎁 <b>Новый конкурс</b>\n\nПришлите текст: призы, условия и куда писать за призом "
                  "(например @set_fact). Премиум эмодзи и форматирование сохранятся.", Adm(s="ct"))
        return
    if a == "list":
        await _show_list(cb, session, cid)
        return
    if a == "res":
        await ask(cb, state, "ct_result",
                  "✏️ <b>Текст поздравления</b>\n\nПришлите новый текст. Вместо имени победителя поставьте "
                  "<code>{winner}</code>: бот подставит кликабельное имя.", Adm(s="ct"), cid=cid)
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
        await session.commit()
        await svc.congratulate(cb.bot, winner)
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


async def _show_list(cb: CallbackQuery, session: AsyncSession, cid: int) -> None:
    uids = (await session.execute(
        select(ContestEntry.user_id).where(ContestEntry.contest_id == cid).order_by(ContestEntry.id))).scalars().all()
    users = {}
    if uids:
        users = {u.id: u for u in (await session.execute(select(User).where(User.id.in_(uids)))).scalars().all()}
    lines = [f"{i}. {svc.mention(uid, svc.name_of(users.get(uid), uid))}" for i, uid in enumerate(uids[:60], 1)]
    more = f"\n… и ещё {len(uids) - 60}" if len(uids) > 60 else ""
    text = f"👥 <b>Участники</b> ({len(uids)})\n\n" + ("\n".join(lines) or "Пока никого.") + more
    await show(cb, text, kb([btn("◀️ Назад", Adm(s="ct"))]))


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
    await show(ctx.target, preview,
               kb([btn("🚀 Запустить рассылку", Adm(s="ct", a="start", i=cid))],
                  [btn("◀️ Отмена", Adm(s="ct", a="drop", i=cid))]))


@op("ct_result")
async def op_ct_result(ctx: Ctx) -> None:
    msg = ctx.message
    html = (msg.html_text if msg is not None and msg.text else (ctx.text or "")).strip()
    if not html or len(html) > 1000:
        await say(ctx.target, "Нужен текст до 1000 символов. Пришлите ещё раз:")
        return
    c = await ctx.session.get(Contest, ctx.data["cid"])
    if c is not None:
        c.result = html
        await ctx.session.commit()
    await ctx.state.clear()
    await view(ctx.target, ctx.session, Adm(s="ct"))
