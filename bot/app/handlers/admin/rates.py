import re
from decimal import Decimal

from aiogram import F, Router
from aiogram.types import CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...cb import Adm
from ...db.models import Rate
from ...services import posting, settings
from ...ui import btn, kb, show
from ...utils import Rich, entities_from_store, h, money, num, parse_number, rich_store
from .common import Ctx, ask, op, screen

router = Router(name="admin_rates")

PLACEHOLDERS = (
    "{date} дата · {rates} список курсов · {stars_min} цена звезды от · {sla_exchange} срок обмена · "
    "{sla_stars} срок звёзд · {ton} курс TON · {bot} юзернейм бота · {brand} название"
)


@screen("rates")
async def view(target, session: AsyncSession, cbd: Adm) -> None:
    if cbd.a == "card":
        await rate_card(target, session, cbd.i)
        return
    rates = (await session.execute(select(Rate).order_by(Rate.sort, Rate.id))).scalars().all()
    b = InlineKeyboardBuilder()
    for r in rates:
        mark = "" if r.is_active else "🙈 "
        b.row(btn(f"{mark}{r.code} · покупка {num(r.buy)} · продажа {num(r.sell)}", Adm(s="rates", a="card", i=r.id)))
    b.row(btn("➕ Добавить валюту", Adm(s="rates", a="add")))
    ton = settings.get("ton_kzt")
    b.row(btn(f"💎 Курс TON: {money(ton) if ton else 'не задан'}", Adm(s="rates", a="ton")))
    b.row(btn("📢 Курсы в канал", Adm(s="rates", a="post")), btn("🧾 Шаблон поста", Adm(s="rates", a="tpl")))
    b.row(btn("⚙️ Админка", Adm(s="menu")))
    await show(
        target,
        "💱 <b>Курсы обмена</b>\n\n"
        "Покупка: по какому курсу вы покупаете у клиента.\nПродажа: по какому курсу продаёте клиенту.\n"
        "Курс TON нужен, чтобы показывать цены юзеров в тенге.\n\nНажмите на валюту, чтобы изменить курс:",
        b.as_markup(),
    )


async def rate_card(target, session: AsyncSession, rate_id: int) -> None:
    r = await session.get(Rate, rate_id)
    if not r:
        await view(target, session, Adm(s="rates"))
        return
    text = (
        f"💱 <b>{h(r.code)}</b>\n\n"
        f"🔴 Покупка (у клиента): <b>{num(r.buy)} ₸</b>\n"
        f"🟢 Продажа (клиенту): <b>{num(r.sell)} ₸</b>\n"
        f"📦 Минимум: <b>{num(r.min_qty)}</b>\n"
        f"👁 Видимость: <b>{'показывается' if r.is_active else 'скрыта'}</b>"
    )
    await show(target, text, kb(
        [btn("✏️ Покупка", Adm(s="rates", a="buy", i=r.id)), btn("✏️ Продажа", Adm(s="rates", a="sell", i=r.id))],
        [btn("✏️ Минимум", Adm(s="rates", a="min", i=r.id)), btn("🔼 Выше в списке", Adm(s="rates", a="up", i=r.id))],
        [btn("🙈 Скрыть" if r.is_active else "👁 Показать", Adm(s="rates", a="toggle", i=r.id)),
         btn("🗑 Удалить", Adm(s="rates", a="del", i=r.id))],
        [btn("◀️ Курсы", Adm(s="rates"))],
    ))


@router.callback_query(Adm.filter(F.s == "rates"))
async def on_rates(cb: CallbackQuery, callback_data: Adm, session: AsyncSession, state) -> None:
    a, rid = callback_data.a, callback_data.i
    back = Adm(s="rates", a="card", i=rid)
    if a in ("", "card"):
        await view(cb, session, callback_data)
    elif a == "add":
        await ask(cb, state, "rate_add", "➕ Введите код валюты, например <code>USDT</code>, <code>BTC</code>, <code>RUB</code>:",
                  Adm(s="rates"))
    elif a in ("buy", "sell", "min"):
        label = {"buy": "курс покупки у клиента", "sell": "курс продажи клиенту", "min": "минимальное количество"}[a]
        await ask(cb, state, "rate_field", f"✏️ Введите {label} в ₸ (или «-», чтобы убрать):", back, rate_id=rid, field=a)
    elif a == "toggle":
        r = await session.get(Rate, rid)
        if r:
            r.is_active = not r.is_active
            await session.commit()
        await rate_card(cb, session, rid)
    elif a == "up":
        rates = (await session.execute(select(Rate).order_by(Rate.sort, Rate.id))).scalars().all()
        ids = [r.id for r in rates]
        if rid in ids:
            i = ids.index(rid)
            if i > 0:
                ids[i - 1], ids[i] = ids[i], ids[i - 1]
            for n, r_id in enumerate(ids):
                next(r for r in rates if r.id == r_id).sort = n
            await session.commit()
        await rate_card(cb, session, rid)
    elif a == "del":
        await show(cb, "Удалить валюту?", kb([btn("🗑 Да", Adm(s="rates", a="del_ok", i=rid))], [btn("◀️ Нет", back)]))
    elif a == "del_ok":
        r = await session.get(Rate, rid)
        if r:
            await session.delete(r)
            await session.commit()
        await view(cb, session, Adm(s="rates"))
    elif a == "ton":
        await ask(cb, state, "set_ton", "💎 Введите курс 1 TON в тенге, например <code>1450</code>:", Adm(s="rates"))
    elif a == "post":
        text, ents = await posting.rates_post(session, cb.bot)
        await show(cb, Rich(text, entities_from_store(ents)), kb(
            [btn("📢 Опубликовать", Adm(s="rates", a="post_ok"))],
            [btn("🧾 Изменить шаблон", Adm(s="rates", a="tpl"))],
            [btn("◀️ Курсы", Adm(s="rates"))],
        ))
    elif a == "post_ok":
        text, ents = await posting.rates_post(session, cb.bot)
        ok, info = await posting.publish(session, cb.bot, text, ents, kind="rates")
        await show(cb, ("✅ " if ok else "⚠️ ") + h(info), kb([btn("◀️ Курсы", Adm(s="rates"))]))
    elif a == "tpl":
        await ask(
            cb, state, "rates_tpl",
            "🧾 <b>Шаблон поста с курсами</b>\n\n"
            "Пришлите текст поста. Можно с премиум эмодзи и форматированием, всё сохранится.\n\n"
            f"Подстановки: {h(PLACEHOLDERS)}\n\nНажмите «Пропустить», чтобы вернуть стандартный шаблон.",
            Adm(s="rates"), skip=True,
        )


@op("rate_add")
async def op_rate_add(ctx: Ctx) -> None:
    code = re.sub(r"[^A-Za-z0-9]", "", ctx.text or "").upper()[:16]
    if not code:
        await ctx.target.answer("Код из латинских букв, например <code>USDT</code>:")
        return
    await ctx.state.clear()
    sort = (await ctx.session.scalar(select(func.max(Rate.sort)))) or 0
    rate = Rate(code=code, sort=sort + 1)
    ctx.session.add(rate)
    await ctx.session.commit()
    await rate_card(ctx.target, ctx.session, rate.id)


@op("rate_field")
async def op_rate_field(ctx: Ctx) -> None:
    raw = (ctx.text or "").strip()
    value = None if raw == "-" else parse_number(raw)
    if raw != "-" and value is None:
        await ctx.target.answer("Нужно число, например <code>471.5</code>, или «-»:")
        return
    await ctx.state.clear()
    r = await ctx.session.get(Rate, int(ctx.data["rate_id"]))
    if r:
        field = {"buy": "buy", "sell": "sell", "min": "min_qty"}[ctx.data["field"]]
        setattr(r, field, value)
        await ctx.session.commit()
    await rate_card(ctx.target, ctx.session, int(ctx.data["rate_id"]))


@op("set_ton")
async def op_set_ton(ctx: Ctx) -> None:
    value = parse_number(ctx.text)
    if value is None:
        await ctx.target.answer("Нужно число, например <code>1450</code>:")
        return
    await ctx.state.clear()
    await settings.put(ctx.session, "ton_kzt", float(value))
    await ctx.session.commit()
    await view(ctx.target, ctx.session, Adm(s="rates"))


@op("rates_tpl")
async def op_rates_tpl(ctx: Ctx) -> None:
    await ctx.state.clear()
    if ctx.message is None:
        await settings.reset(ctx.session, "rates_template")
    else:
        entities = ctx.message.entities if ctx.message.text else ctx.message.caption_entities
        await settings.put(ctx.session, "rates_template", rich_store(ctx.text or "", entities))
    await ctx.session.commit()
    await on_preview(ctx)


async def on_preview(ctx: Ctx) -> None:
    text, ents = await posting.rates_post(ctx.session, ctx.bot)
    await show(ctx.target, Rich(text, entities_from_store(ents)), kb(
        [btn("📢 Опубликовать", Adm(s="rates", a="post_ok"))],
        [btn("◀️ Курсы", Adm(s="rates"))],
    ))


# ---------------- Звёзды ----------------


@screen("stars")
async def stars_view(target, session: AsyncSession, cbd: Adm) -> None:
    tiers = settings.star_tiers()
    lines = "\n".join(f"• от {num(q)} шт: {num(p)} ₸" for q, p in tiers)
    presets = ", ".join(str(x) for x in settings.get("star_presets") or [])
    await show(
        target,
        "⭐ <b>Звёзды</b>\n\n"
        f"<b>Сетка цен</b> (за 1 звезду):\n{lines}\n\n"
        f"<b>Кнопки количества:</b> {h(presets)}\n"
        f"<b>Выдача звёзд:</b> {h(settings.get('sla_stars'))}\n"
        f"<b>Срок обмена:</b> {h(settings.get('sla_exchange'))}\n"
        f"<b>Передача подарков:</b> {h(settings.get('sla_gifts'))}"
        + ("" if settings.is_set("star_tiers") else "\n\n⚠️ <b>Сейчас стоят цены по умолчанию.</b> Нажмите «Сетка цен» и задайте свои."),
        kb(
            [btn("✏️ Сетка цен", Adm(s="stars", a="tiers")), btn("✏️ Кнопки", Adm(s="stars", a="presets"))],
            [btn("⏱ Срок звёзд", Adm(s="stars", a="sla", v="sla_stars")),
             btn("⏱ Срок обмена", Adm(s="stars", a="sla", v="sla_exchange"))],
            [btn("⏱ Срок подарков", Adm(s="stars", a="sla", v="sla_gifts"))],
            [btn("⚙️ Админка", Adm(s="menu"))],
        ),
    )


@router.callback_query(Adm.filter(F.s == "stars"))
async def on_stars(cb: CallbackQuery, callback_data: Adm, session: AsyncSession, state) -> None:
    back = Adm(s="stars")
    if callback_data.a == "tiers":
        await ask(cb, state, "star_tiers",
                  "✏️ Пришлите сетку: каждая строка «от скольки штук» и «цена за звезду».\n\n"
                  "Пример:\n<code>500 20\n1000 19.5\n5000 19</code>\n\nПервая строка задаёт минимальный заказ.",
                  back)
    elif callback_data.a == "presets":
        await ask(cb, state, "star_presets", "✏️ Пришлите количества для кнопок через пробел:\n<code>50 100 250 500 1000 2500 5000</code>", back)
    elif callback_data.a == "sla" and callback_data.v in ("sla_stars", "sla_exchange", "sla_gifts"):
        await ask(cb, state, "sla", "⏱ Введите срок текстом, например «до 3 часов»:", back, key=callback_data.v)
    else:
        await stars_view(cb, session, callback_data)


@op("star_tiers")
async def op_tiers(ctx: Ctx) -> None:
    tiers = []
    for line in (ctx.text or "").splitlines():
        parts = line.replace(",", ".").split()
        if len(parts) >= 2:
            try:
                q, p = int(parts[0]), float(Decimal(parts[1]))
            except Exception:
                continue
            if q > 0 and p > 0:
                tiers.append([q, p])
    if not tiers:
        await ctx.target.answer("Не нашёл ни одной строки. Формат: <code>50 9.5</code>")
        return
    await ctx.state.clear()
    await settings.put(ctx.session, "star_tiers", sorted(tiers))
    await ctx.session.commit()
    await stars_view(ctx.target, ctx.session, Adm(s="stars"))


@op("star_presets")
async def op_presets(ctx: Ctx) -> None:
    values = sorted({int(x) for x in re.findall(r"\d+", ctx.text or "") if 0 < int(x) <= 1_000_000})
    if not values:
        await ctx.target.answer("Пришлите числа через пробел:")
        return
    await ctx.state.clear()
    await settings.put(ctx.session, "star_presets", values[:12])
    await ctx.session.commit()
    await stars_view(ctx.target, ctx.session, Adm(s="stars"))


@op("sla")
async def op_sla(ctx: Ctx) -> None:
    if not ctx.text:
        await ctx.target.answer("Введите текст:")
        return
    await ctx.state.clear()
    await settings.put(ctx.session, ctx.data["key"], ctx.text.strip()[:100])
    await ctx.session.commit()
    await stars_view(ctx.target, ctx.session, Adm(s="stars"))
