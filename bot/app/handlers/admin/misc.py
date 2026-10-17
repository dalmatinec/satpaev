"""Рефералы, отзывы, бэкапы и настройки."""

import re

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ...cb import Adm
from ...db.models import Order, RefAccrual, Review, User
from ...services import backup, posting, settings
from ...services.reviews import review_post, reviews_target
from ...ui import answer, btn, kb, send_safe, show
from ...utils import h, money, num, parse_number
from .common import Ctx, ask, op, screen

router = Router(name="admin_misc")


# ---------------- Рефералы ----------------

@screen("ref")
async def ref_view(target, session: AsyncSession, cbd: Adm) -> None:
    pending = (await session.execute(
        select(RefAccrual.referrer_id, func.sum(RefAccrual.amount), func.count(RefAccrual.id))
        .where(RefAccrual.paid.is_(False)).group_by(RefAccrual.referrer_id)
        .order_by(func.sum(RefAccrual.amount).desc()).limit(10)
    )).all()
    top = (await session.execute(
        select(User.referrer_id, func.count(User.id)).where(User.referrer_id.is_not(None))
        .group_by(User.referrer_id).order_by(func.count(User.id).desc()).limit(5)
    )).all()
    users = {}
    ids = {r[0] for r in pending} | {r[0] for r in top}
    if ids:
        users = {u.id: u for u in (await session.execute(select(User).where(User.id.in_(ids)))).scalars().all()}
    base = "прибыли" if settings.get("ref_base") == "profit" else "суммы заказа"
    lines = [f"👥 <b>Рефералы</b>\n", f"Начисление: <b>{num(settings.get('ref_percent'))}%</b> от {base}\n"]
    if top:
        lines.append("<b>Топ по приглашениям</b>")
        for rid, cnt in top:
            u = users.get(rid)
            lines.append(f"• {h(u.mention if u else rid)}: {cnt}")
    b = InlineKeyboardBuilder()
    if pending:
        lines.append("\n<b>К выплате</b> (нажмите, когда выплатили)")
        for rid, total, cnt in pending:
            u = users.get(rid)
            b.row(btn(f"💸 {u.mention if u else rid} · {money(total)} ({cnt})", Adm(s="ref", a="pay", i=rid)))
    b.row(btn("✏️ Процент", Adm(s="ref", a="pct")),
          btn("🔁 От " + ("суммы" if settings.get("ref_base") == "profit" else "прибыли"), Adm(s="ref", a="base")))
    b.row(btn("◀️ Ещё", Adm(s="more")))
    await show(target, "\n".join(lines), b.as_markup())


@router.callback_query(Adm.filter(F.s == "ref"))
async def on_ref(cb: CallbackQuery, callback_data: Adm, session: AsyncSession, state: FSMContext) -> None:
    a = callback_data.a
    if a == "pct":
        await ask(cb, state, "ref_pct", "✏️ Введите процент начисления рефереру, например <code>5</code>:", Adm(s="ref"))
        return
    if a == "base":
        await settings.put(session, "ref_base", "amount" if settings.get("ref_base") == "profit" else "profit")
        await session.commit()
    elif a == "pay":
        u = await session.get(User, callback_data.i)
        total = await session.scalar(select(func.sum(RefAccrual.amount)).where(
            RefAccrual.referrer_id == callback_data.i, RefAccrual.paid.is_(False)))
        await show(cb, f"Отметить выплату {money(total)} для {h(u.mention if u else callback_data.i)}?", kb(
            [btn("✅ Да, выплачено", Adm(s="ref", a="pay_ok", i=callback_data.i))], [btn("◀️ Нет", Adm(s="ref"))]))
        return
    elif a == "pay_ok":
        total = await session.scalar(select(func.sum(RefAccrual.amount)).where(
            RefAccrual.referrer_id == callback_data.i, RefAccrual.paid.is_(False)))
        await session.execute(update(RefAccrual).where(
            RefAccrual.referrer_id == callback_data.i, RefAccrual.paid.is_(False)).values(paid=True))
        await session.commit()
        if total:
            await send_safe(cb.bot, callback_data.i, settings.t("ref_paid", amount=money(total)))
    await ref_view(cb, session, Adm(s="ref"))


@op("ref_pct")
async def op_ref_pct(ctx: Ctx) -> None:
    value = parse_number(ctx.text)
    if value is None or value > 100:
        await ctx.target.answer("Число от 0 до 100:")
        return
    await ctx.state.clear()
    await settings.put(ctx.session, "ref_percent", float(value))
    await ctx.session.commit()
    await ref_view(ctx.target, ctx.session, Adm(s="ref"))


# ---------------- Отзывы ----------------

@screen("rev")
async def rev_view(target, session: AsyncSession, cbd: Adm) -> None:
    counts = dict((await session.execute(select(Review.status, func.count(Review.id)).group_by(Review.status))).all())
    r = await session.scalar(select(Review).where(Review.status == "new").order_by(Review.id).limit(1))
    head = (f"📝 <b>Отзывы</b>\n\nНовых: <b>{counts.get('new', 0)}</b> · опубликовано: <b>{counts.get('published', 0)}</b> · "
            f"скрыто: <b>{counts.get('hidden', 0)}</b>")
    if not r:
        await show(target, head + "\n\nНовых отзывов нет.", kb([btn("⚙️ Админка", Adm(s="menu"))]))
        return
    u = await session.get(User, r.user_id)
    text = (head + f"\n\n{'⭐' * r.rating} · заказ #{r.order_id}\n{h(u.full_name if u else '')} ({h(u.mention if u else '')})\n\n"
            + (f"«{h(r.text)}»" if r.text else "<i>без текста</i>"))
    await show(target, text, kb(
        [btn("📢 Опубликовать в канал", Adm(s="rev", a="pub", i=r.id))],
        [btn("✅ Одобрить без поста", Adm(s="rev", a="ok", i=r.id)), btn("🙈 Скрыть", Adm(s="rev", a="hide", i=r.id))],
        [btn("⚙️ Админка", Adm(s="menu"))],
    ))


@router.callback_query(Adm.filter(F.s == "rev"))
async def on_rev(cb: CallbackQuery, callback_data: Adm, session: AsyncSession) -> None:
    r = await session.get(Review, callback_data.i) if callback_data.i else None
    if r and callback_data.a == "pub":
        u = await session.get(User, r.user_id)
        order = await session.get(Order, r.order_id)
        text, ents = review_post(r, u, order)
        ok, info = await posting.publish(session, cb.bot, text, ents, kind="review", target=reviews_target())
        if ok:
            r.status = "published"
            await session.commit()
        await answer(cb, info[:190], alert=not ok)
    elif r and callback_data.a == "ok":
        r.status = "published"
        await session.commit()
    elif r and callback_data.a == "hide":
        r.status = "hidden"
        await session.commit()
    await rev_view(cb, session, Adm(s="rev"))


# ---------------- Бэкапы ----------------

@screen("bk")
async def bk_view(target, session: AsyncSession, cbd: Adm) -> None:
    last = settings.get("backup_last") or {}
    info = (f"{h(last.get('file'))} · {backup.size_text(last.get('size'))}" if last.get("file") else "ещё не было")
    await show(
        target,
        "💾 <b>Бэкапы</b>\n\n"
        f"Каждый день в <b>{h(settings.get('backup_time'))}</b> бот делает бэкап базы, кладёт его на сервер в папку "
        "<code>backups</code> и присылает файл вам в личку. Прошлый бэкап удаляется и там, и там.\n\n"
        f"Последний: <b>{info}</b>\n\n"
        "♻️ <b>Восстановление</b>\nПоложите файл в папку <code>backups</code> на сервере и выполните:\n"
        "<code>./restore.sh</code>",
        kb(
            [btn("💾 Сделать бэкап сейчас", Adm(s="bk", a="now"))],
            [btn("⏰ Изменить время", Adm(s="bk", a="time"))],
            [btn("◀️ Ещё", Adm(s="more"))],
        ),
    )


@router.callback_query(Adm.filter(F.s == "bk"))
async def on_bk(cb: CallbackQuery, callback_data: Adm, session: AsyncSession, state: FSMContext, sm) -> None:
    if callback_data.a == "now":
        await show(cb, "⏳ Делаю бэкап...")
        ok, info = await backup.make_backup(cb.bot, sm)
        await show(cb, ("✅ Готово: " if ok else "⚠️ Ошибка: ") + h(info), kb([btn("◀️ Бэкапы", Adm(s="bk"))]))
    elif callback_data.a == "time":
        await ask(cb, state, "set_time", "⏰ Во сколько делать бэкап? Формат <code>04:00</code>:", Adm(s="bk"), key="backup_time")
    else:
        await bk_view(cb, session, callback_data)


# ---------------- Настройки ----------------

def _onoff(v) -> str:
    return "вкл" if v else "выкл"


@screen("set")
async def set_view(target, session: AsyncSession, cbd: Adm) -> None:
    site = settings.get("site_url") or "нет"
    text = (
        "⚙️ <b>Настройки</b>\n\n"
        f"🏷 Название: <b>{h(settings.get('brand'))}</b>\n"
        f"🕐 Рабочее время: <b>{_onoff(settings.get('work_enabled'))}</b>, "
        f"с <b>{h(settings.get('work_from'))}</b> до <b>{h(settings.get('work_to'))}</b>\n"
        f"💎 Наценка на юзеры: <b>x{num(settings.get('uname_markup'))}</b>\n"
        f"🔒 Удержание юзера до аукциона: <b>{num(settings.get('uname_hold_days'))} дн.</b>\n"
        f"🔨 Длительность аукциона: <b>{num(settings.get('uname_auction_days'))} дн.</b>\n"
        f"📢 Канал: {h(settings.get('channel_link') or 'нет')}\n"
        f"📝 Отзывы: {h(settings.get('reviews_link') or 'нет')}\n"
        f"🌐 Сайт: {h(site)}\n\n"
        "Тексты, кнопки и картинки меняются в «🧩 Ещё»."
    )
    await show(target, text, kb(
        [btn("🏷 Название", Adm(s="set", a="brand"))],
        [btn(f"🕐 Время работы: {_onoff(settings.get('work_enabled'))}", Adm(s="set", a="work"))],
        [btn("▶️ Начало", Adm(s="set", a="time", v="work_from")), btn("⏹ Конец", Adm(s="set", a="time", v="work_to"))],
        [btn("💎 Наценка", Adm(s="set", a="num", v="uname_markup")),
         btn("🔒 Дни", Adm(s="set", a="num", v="uname_hold_days")),
         btn("🔨 Дни", Adm(s="set", a="num", v="uname_auction_days"))],
        [btn("📢 Ссылка канала", Adm(s="set", a="url", v="channel_link")),
         btn("📝 Ссылка отзывов", Adm(s="set", a="url", v="reviews_link"))],
        [btn("🌐 Ссылка сайта", Adm(s="set", a="url", v="site_url"))],
        [btn("◀️ Ещё", Adm(s="more"))],
    ))


NUM_LABELS = {
    "uname_markup": "наценку на готовые юзеры (множитель, например 2)",
    "uname_hold_days": "через сколько дней после «Занят» напомнить про аукцион",
    "uname_auction_days": "сколько дней длится аукцион",
}


@router.callback_query(Adm.filter(F.s == "set"))
async def on_set(cb: CallbackQuery, callback_data: Adm, session: AsyncSession, state: FSMContext) -> None:
    a, key = callback_data.a, callback_data.v
    back = Adm(s="set")
    if a == "brand":
        await ask(cb, state, "set_text", "🏷 Введите название магазина:", back, key="brand")
    elif a == "work":
        await settings.put(session, "work_enabled", not settings.get("work_enabled"))
        await session.commit()
        await set_view(cb, session, back)
    elif a == "time" and key in ("work_from", "work_to"):
        await ask(cb, state, "set_time", "🕐 Введите время в формате <code>10:00</code>:", back, key=key)
    elif a == "num" and key in NUM_LABELS:
        await ask(cb, state, "set_num", f"✏️ Введите {NUM_LABELS[key]}:", back, key=key)
    elif a == "url" and key in ("channel_link", "reviews_link", "site_url"):
        await ask(cb, state, "set_url", "🔗 Пришлите ссылку (https://... или t.me/...). «Пропустить» уберёт ссылку.",
                  back, skip=True, key=key)
    else:
        await set_view(cb, session, back)


async def _back(ctx: Ctx) -> None:
    await ctx.state.clear()
    await ctx.session.commit()
    await ctx.back()


@op("set_text")
async def op_set_text(ctx: Ctx) -> None:
    if not ctx.text:
        await ctx.target.answer("Пришлите текст:")
        return
    await settings.put(ctx.session, ctx.data["key"], ctx.text.strip()[:64])
    await _back(ctx)


@op("set_time")
async def op_set_time(ctx: Ctx) -> None:
    m = re.fullmatch(r"\s*(\d{1,2})[:.](\d{2})\s*", ctx.text or "")
    if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
        await ctx.target.answer("Формат времени <code>10:00</code>:")
        return
    await settings.put(ctx.session, ctx.data["key"], f"{int(m.group(1)):02d}:{m.group(2)}")
    await _back(ctx)


@op("set_num")
async def op_set_num(ctx: Ctx) -> None:
    value = parse_number(ctx.text)
    if value is None or value > 1000:
        await ctx.target.answer("Нужно число:")
        return
    await settings.put(ctx.session, ctx.data["key"], float(value))
    await _back(ctx)


@op("set_url")
async def op_set_url(ctx: Ctx) -> None:
    if ctx.message is None:
        await settings.put(ctx.session, ctx.data["key"], "")
        await _back(ctx)
        return
    value = (ctx.text or "").strip()
    if value.startswith("t.me/"):
        value = "https://" + value
    if not value.startswith(("http://", "https://")):
        await ctx.target.answer("Ссылка должна начинаться с https:// или t.me/")
        return
    await settings.put(ctx.session, ctx.data["key"], value[:256])
    await _back(ctx)

