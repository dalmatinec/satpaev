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
from ...services.reviews import first_name, name_html, review_post, reviews_target
from ...ui import answer, btn, kb, send_safe, show
from ...utils import fdate, h, money, num, parse_number
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

REV_TABS = {"new": "🆕 Новые", "published": "✅ Опубликованные", "hidden": "🙈 Скрытые"}
REV_PER_PAGE = 5


@screen("rev")
async def rev_view(target, session: AsyncSession, cbd: Adm) -> None:
    if cbd.a == "card":
        await rev_card(target, session, cbd.i)
        return
    tab = cbd.v if cbd.v in REV_TABS else "new"
    counts = dict((await session.execute(select(Review.status, func.count(Review.id)).group_by(Review.status))).all())
    total = counts.get(tab, 0)
    pages = max(1, (total + REV_PER_PAGE - 1) // REV_PER_PAGE)
    page = max(0, min(cbd.p, pages - 1))
    rows = (await session.execute(
        select(Review, User).join(User, User.id == Review.user_id, isouter=True)
        .where(Review.status == tab).order_by(Review.created_at.desc())
        .offset(page * REV_PER_PAGE).limit(REV_PER_PAGE)
    )).all()
    lines = []
    b = InlineKeyboardBuilder()
    for r, u in rows:
        lines.append(f"{'⭐' * r.rating} · {name_html(u)} · {fdate(r.created_at)}"
                     + (f"\n«{h(r.text[:120])}»" if r.text else ""))
        b.row(btn(f"{'⭐' * r.rating} #{r.id} {first_name(u)}", Adm(s="rev", a="card", i=r.id, v=tab, p=page)))
    tabs = [btn(("• " if k == tab else "") + f"{name} ({counts.get(k, 0)})", Adm(s="rev", v=k)) for k, name in REV_TABS.items()]
    b.row(*tabs[:2])
    b.row(tabs[2])
    if pages > 1:
        nav = []
        if page > 0:
            nav.append(btn("◀️", Adm(s="rev", v=tab, p=page - 1)))
        nav.append(btn(f"{page + 1}/{pages}", Adm(s="rev", v=tab, p=page)))
        if page < pages - 1:
            nav.append(btn("▶️", Adm(s="rev", v=tab, p=page + 1)))
        b.row(*nav)
    names = "ссылкой на профиль" if settings.get("reviews_names") == "link" else "скрыты (Ал***)"
    who = "все клиенты" if settings.get("reviews_mode") == "all" else "только после заказа"
    b.row(btn(f"👤 Имена: {names}", Adm(s="rev", a="names", v=tab)))
    b.row(btn(f"✍️ Оставлять могут: {who}", Adm(s="rev", a="mode", v=tab)))
    b.row(btn("🔗 Ссылка на канал отзывов", Adm(s="set", a="url", v="reviews_link")))
    b.row(btn("⚙️ Админка", Adm(s="menu")))
    text = f"📝 <b>Отзывы</b> · {REV_TABS[tab]}: <b>{total}</b>\n\n" + ("\n\n".join(lines) or "Здесь пусто.")
    await show(target, text, b.as_markup())


async def rev_card(target, session: AsyncSession, review_id: int, tab: str = "new", page: int = 0) -> None:
    r = await session.get(Review, review_id)
    if not r:
        await rev_view(target, session, Adm(s="rev", v=tab))
        return
    u = await session.get(User, r.user_id)
    status = {"new": "🆕 новый", "published": "✅ опубликован", "hidden": "🙈 скрыт"}.get(r.status, r.status)
    order = f"заказ #{r.order_id}" if r.order_id else "без заказа"
    text = (
        f"📝 <b>Отзыв #{r.id}</b> · {status}\n"
        f"{'⭐' * r.rating} · {order}\n"
        f"👤 {name_html(u)} ({h(u.mention if u else '')}) · <code>{r.user_id}</code>\n"
        f"📅 {fdate(r.created_at)}\n\n"
        + (f"«{h(r.text)}»" if r.text else "<i>без текста</i>")
    )
    rows = []
    if r.status != "published":
        rows.append([btn("📢 Опубликовать в канал", Adm(s="rev", a="pub", i=r.id, v=tab, p=page))])
        rows.append([btn("✅ Показать в боте без поста", Adm(s="rev", a="ok", i=r.id, v=tab, p=page))])
    if r.status != "hidden":
        rows.append([btn("🙈 Скрыть", Adm(s="rev", a="hide", i=r.id, v=tab, p=page))])
    rows.append([btn("🗑 Удалить", Adm(s="rev", a="del", i=r.id, v=tab, p=page)),
                 btn("👤 Клиент", Adm(s="cl", a="card", i=r.user_id))])
    rows.append([btn("◀️ К списку", Adm(s="rev", v=tab, p=page))])
    await show(target, text, kb(*rows))


@router.callback_query(Adm.filter(F.s == "rev"))
async def on_rev(cb: CallbackQuery, callback_data: Adm, session: AsyncSession) -> None:
    a, tab, page = callback_data.a, callback_data.v, callback_data.p
    if a in ("", "card") and not (a == "card" and callback_data.i):
        await rev_view(cb, session, callback_data)
        return
    if a == "names":
        await settings.put(session, "reviews_names", "mask" if settings.get("reviews_names") == "link" else "link")
        await session.commit()
        await rev_view(cb, session, Adm(s="rev", v=tab))
        return
    if a == "mode":
        await settings.put(session, "reviews_mode", "orders" if settings.get("reviews_mode") == "all" else "all")
        await session.commit()
        await rev_view(cb, session, Adm(s="rev", v=tab))
        return
    r = await session.get(Review, callback_data.i) if callback_data.i else None
    if not r:
        await rev_view(cb, session, Adm(s="rev", v=tab))
        return
    if a == "card":
        await rev_card(cb, session, r.id, tab, page)
        return
    if a == "pub":
        u = await session.get(User, r.user_id)
        order = await session.get(Order, r.order_id) if r.order_id else None
        text, ents = review_post(r, u, order)
        ok, info = await posting.publish(session, cb.bot, text, ents, kind="review", target=reviews_target())
        if ok:
            r.status = "published"
            await session.commit()
        await answer(cb, info[:190], alert=not ok)
    elif a == "ok":
        r.status = "published"
        await session.commit()
        await answer(cb, "Отзыв виден в боте")
    elif a == "hide":
        r.status = "hidden"
        await session.commit()
        await answer(cb, "Отзыв скрыт")
    elif a == "del":
        await show(cb, f"Удалить отзыв #{r.id} насовсем?", kb(
            [btn("🗑 Да, удалить", Adm(s="rev", a="del_ok", i=r.id, v=tab, p=page))],
            [btn("◀️ Нет", Adm(s="rev", a="card", i=r.id, v=tab, p=page))],
        ))
        return
    elif a == "del_ok":
        await session.delete(r)
        await session.commit()
        await answer(cb, "Удалено")
        await rev_view(cb, session, Adm(s="rev", v=tab, p=page))
        return
    await rev_card(cb, session, r.id, tab, page)


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
        f"💰 Минимальный заказ: <b>{money(settings.min_order())}</b>\n"
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
        [btn("🏷 Название", Adm(s="set", a="brand")), btn("💰 Мин. заказ", Adm(s="set", a="num", v="min_order"))],
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
    "min_order": "минимальную сумму любого заказа в тенге, например 10000",
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
    limit = 10 ** 9 if ctx.data["key"] == "min_order" else 1000
    if value is None or value > limit:
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

