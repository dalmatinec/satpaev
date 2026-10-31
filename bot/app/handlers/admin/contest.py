"""Админка: конкурс. Текст и время, предпросмотр, рассылка клиентам, итоги по таймеру."""

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...cb import Adm
from ...db.models import Contest, ContestEntry
from ...services import contest as svc
from ...ui import answer, btn, kb, say, show
from ...utils import utcnow
from .common import Ctx, ask, op, screen

router = Router(name="admin_contest")


async def _active(session: AsyncSession):
    return await session.scalar(select(Contest).where(Contest.status == "active").limit(1))


@screen("ct")
async def view(target, session: AsyncSession, cbd: Adm) -> None:
    active = await _active(session)
    if active:
        count = await session.scalar(
            select(func.count(ContestEntry.id)).where(ContestEntry.contest_id == active.id)) or 0
        text = (f"🎁 <b>Конкурс идёт</b>\n\nУчастников: <b>{count}</b>\n"
                f"Итоги: <b>{svc.deadline_text(active)}</b>, бот выберет победителя сам.")
        rows = [[btn("🎲 Подвести итоги сейчас", Adm(s="ct", a="end", i=active.id))],
                [btn("⏹ Отменить конкурс", Adm(s="ct", a="cancel", i=active.id))]]
    else:
        text = "🎁 <b>Конкурс</b>\n\nСейчас конкурса нет."
        last = await session.scalar(
            select(Contest).where(Contest.status == "finished").order_by(Contest.id.desc()).limit(1))
        if last and last.winner_id:
            from ...db.models import User

            name = svc.name_of(await session.get(User, last.winner_id), last.winner_id)
            text += f"\n\nПрошлый конкурс: {svc.deadline_text(last)}, победитель: {svc.mention(last.winner_id, name)}"
        rows = []
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
                  "(например @set_fact). Можно с жирным шрифтом и ссылками. Премиум эмодзи не сохранятся: "
                  "добавьте их в канале сами.", Adm(s="ct"))
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


@op("ct_text")
async def op_ct_text(ctx: Ctx) -> None:
    html = ctx.message.html_text if ctx.message is not None and ctx.message.text else (ctx.text or "")
    html = html.strip()
    if not html or len(html) > 3000:
        await say(ctx.target, "Нужен текст до 3000 символов. Пришлите ещё раз:")
        return
    await ask(ctx.target, ctx.state, "ct_time",
              "⏳ Когда подводить итоги?\n\nФормат: <code>ДД.ММ ЧЧ:ММ</code> по времени Алматы, например "
              "<code>05.11 20:00</code>", Adm(s="ct"), text=html)


@op("ct_time")
async def op_ct_time(ctx: Ctx) -> None:
    deadline = svc.parse_deadline(ctx.text)
    if deadline is None:
        await say(ctx.target, "Не понял время, или оно уже прошло. Формат: <code>ДД.ММ ЧЧ:ММ</code>, например "
                              "<code>05.11 20:00</code>")
        return
    c = Contest(text=ctx.data["text"], ends_at=deadline, status="draft")
    ctx.session.add(c)
    await ctx.session.flush()
    cid = c.id
    preview = svc.body(c)
    await ctx.session.commit()
    await ctx.state.clear()
    await show(ctx.target, "👀 <b>Так уйдёт в рассылку:</b>\n\n" + preview,
               kb([btn("🚀 Запустить рассылку", Adm(s="ct", a="start", i=cid))],
                  [btn("◀️ Отмена", Adm(s="ct", a="drop", i=cid))]))
