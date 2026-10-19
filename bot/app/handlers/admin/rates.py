import re
from datetime import datetime
from decimal import Decimal

from aiogram import F, Router
from aiogram.types import CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...cb import Adm
from ...config import config
from ...db.models import Rate
from ...services import posting, settings
from ...ui import answer, btn, kb, say, show
from ...utils import Rich, entities_from_store, h, money, num, parse_number, rich_store
from .common import Ctx, ask, op, screen

router = Router(name="admin_rates")

PLACEHOLDERS = (
    "{date} дата · {time} время · {greeting} приветствие по времени суток · {valid} «с 09:00 до 12:00» · "
    "{rates} список курсов · {stars_min} цена звезды от · {sla_exchange} срок обмена · "
    "{sla_stars} срок звёзд · {ton} курс TON · {fee} сбор за сделку · {bot} юзернейм бота · {brand} название"
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
    b.row(btn("⚡ Обновить все курсы сразу", Adm(s="rates", a="bulk"), style="primary"))
    if not settings.rates_fresh():
        b.row(btn("✅ Курсы на сегодня те же", Adm(s="rates", a="same")))
    b.row(btn("➕ Добавить валюту", Adm(s="rates", a="add")))
    ton = settings.get("ton_kzt")
    b.row(btn(f"💎 Курс TON: {money(ton) if ton else 'не задан'}", Adm(s="rates", a="ton")))
    fee = settings.get("ex_fee") or 0
    b.row(btn(f"🧾 Сбор: {money(fee) if fee else 'нет'}", Adm(s="rates", a="fee")),
          btn("🏷 Название сбора", Adm(s="rates", a="fee_name")))
    b.row(btn("📢 Отправить курсы", Adm(s="rates", a="post"), style="primary"))
    b.row(btn("🧾 Шаблон поста", Adm(s="rates", a="tpl")),
          btn(f"⏳ Действует: {num(settings.get('rates_valid_hours') or 3)} ч", Adm(s="rates", a="valid")))
    b.row(btn("📜 История курсов", Adm(s="rates", a="hist")),
          btn(f"🌙 Сброс в полночь: {'вкл' if settings.get('rates_reset') else 'выкл'}", Adm(s="rates", a="reset")))
    b.row(btn("⚙️ Админка", Adm(s="menu")))
    await show(
        target,
        "💱 <b>Курсы обмена</b>\n"
        + (f"📅 Сегодня {datetime.now(config.tz).strftime('%d.%m')}: " + ("✅ курсы обновлены" if settings.rates_fresh()
           else "⚠️ <b>курсы вчерашние</b>, клиенты видят «курс обновляется». Обновите или нажмите «✅ Курсы на сегодня те же»")
           + "\n\n")
        + 
        "Покупка: по какому курсу вы покупаете у клиента.\nПродажа: по какому курсу продаёте клиенту.\n"
        "Курс TON нужен, чтобы показывать цены юзеров в тенге.\n"
        f"🧾 {h(settings.get('ex_fee_name') or 'Сервисный сбор')}: "
        f"<b>{money(settings.get('ex_fee')) if settings.get('ex_fee') else 'нет'}</b> за каждую сделку "
        "(при покупке прибавляется к сумме, при продаже вычитается).\n\nНажмите на валюту, чтобы изменить курс:",
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
        f"📦 Минимальная сделка: <b>{money(r.min_qty) if r.min_qty else 'общий минимум ' + money(settings.min_order())}</b>\n"
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
        label = {"buy": "курс покупки у клиента за 1 монету, в ₸", "sell": "курс продажи клиенту за 1 монету, в ₸",
                 "min": "минимальную сумму сделки по этой валюте в ₸, например <code>15000</code>"}[a]
        await ask(cb, state, "rate_field", f"✏️ Введите {label}. «-» уберёт значение"
                  + (" (тогда действует общий минимальный заказ)." if a == "min" else "."), back, rate_id=rid, field=a)
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
    elif a == "fee":
        await ask(cb, state, "set_num", "🧾 Сколько тенге брать за каждую сделку обмена? Например <code>2500</code>.\n"
                  "<code>0</code> уберёт сбор.", Adm(s="rates"), key="ex_fee")
    elif a == "fee_name":
        await ask(cb, state, "set_text", "🏷 Как называть сбор? Например <code>Сервисный сбор</code>:", Adm(s="rates"),
                  key="ex_fee_name")
    elif a == "ton":
        await ask(cb, state, "set_ton", "💎 Введите курс 1 TON в тенге, например <code>1450</code>:", Adm(s="rates"))
    elif a == "post" and not settings.rates_fresh():
        await show(cb, "⚠️ <b>Курсы вчерашние</b>\n\nСначала обновите их на сегодня или подтвердите, что они те же. "
                       "Так в пост не попадёт старый курс.",
                   kb([btn("⚡ Обновить все курсы сразу", Adm(s="rates", a="bulk"), style="primary")],
                      [btn("✅ Курсы те же, отправить", Adm(s="rates", a="same_post"))],
                      [btn("◀️ Курсы", Adm(s="rates"))]))
    elif a == "same_post":
        await settings.put(session, "rates_day", settings.today())
        await session.commit()
        await on_rates(cb, Adm(s="rates", a="post"), session, state)
    elif a == "post":
        from .channel import start_text_post

        text, ents = await posting.rates_post(session, cb.bot)
        active = (await session.execute(
            select(Rate).where(Rate.is_active.is_(True)).order_by(Rate.sort, Rate.id))).scalars().all()
        from datetime import datetime

        from ...config import config

        snapshot = {"at": datetime.now(config.tz).strftime("%d.%m.%Y %H:%M"),
                    "rates": [[r.code, num(r.buy).replace(".", ",") if r.buy else "",
                               num(r.sell).replace(".", ",") if r.sell else ""] for r in active],
                    "fee": num(settings.get("ex_fee")) if settings.get("ex_fee") else ""}
        await start_text_post(cb, state, session, text, ents, Adm(s="rates"),
                              "👀 <b>Пост с курсами на сегодня</b>", history=snapshot)
    elif a == "hist":
        hist = settings.get("rates_history") or []
        lines = []
        for e in hist[:15]:
            parts = [f"{c} {b or '-'}/{s_ or '-'}" for c, b, s_ in e.get("rates") or []]
            fee = f" · сбор {e['fee']} ₸" if e.get("fee") else ""
            lines.append(f"<b>{h(e.get('at', ''))}</b>\n{h(' · '.join(parts) or 'нет курсов')}{h(fee)}")
        body = "\n\n".join(lines) or "Пока пусто: история появится после первой публикации курсов."
        await show(cb, "📜 <b>История курсов</b>\nпокупаем / продаём, последние публикации\n\n" + body,
                   kb([btn("◀️ Курсы", Adm(s="rates"))]))
    elif a == "same":
        await settings.put(session, "rates_day", settings.today())
        await session.commit()
        await answer(cb, "Курсы подтверждены на сегодня")
        await view(cb, session, Adm(s="rates"))
    elif a == "reset":
        await settings.put(session, "rates_reset", not settings.get("rates_reset"))
        await session.commit()
        await view(cb, session, Adm(s="rates"))
    elif a == "bulk":
        rates = (await session.execute(select(Rate).order_by(Rate.sort, Rate.id))).scalars().all()
        current = "\n".join(f"{r.code} {num(r.buy) if r.buy else '-'} {num(r.sell) if r.sell else '-'}" for r in rates)
        await ask(cb, state, "rates_bulk",
                  "⚡ <b>Курсы на сегодня одним сообщением</b>\n\n"
                  "Каждая строка: <b>валюта · покупаем · продаём</b>. «-» если не меняете в эту сторону.\n"
                  "Новая валюта добавится сама. Можно скопировать текущие и поправить цифры:\n\n"
                  f"<code>{h(current) or 'USDT 440 500'}</code>", Adm(s="rates"))
    elif a == "valid":
        await ask(cb, state, "set_num", "⏳ Сколько часов действует курс после публикации? Например <code>3</code>: "
                  "в посте будет «с 09:00 до 12:00».", Adm(s="rates"), key="rates_valid_hours")
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
        await say(ctx.target, "Код из латинских букв, например <code>USDT</code>:")
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
        await say(ctx.target, "Нужно число, например <code>471.5</code>, или «-»:")
        return
    await ctx.state.clear()
    r = await ctx.session.get(Rate, int(ctx.data["rate_id"]))
    if r:
        field = {"buy": "buy", "sell": "sell", "min": "min_qty"}[ctx.data["field"]]
        setattr(r, field, value)
        if field in ("buy", "sell"):
            await settings.put(ctx.session, "rates_day", settings.today())
        await ctx.session.commit()
    await rate_card(ctx.target, ctx.session, int(ctx.data["rate_id"]))


@op("set_ton")
async def op_set_ton(ctx: Ctx) -> None:
    value = parse_number(ctx.text)
    if value is None:
        await say(ctx.target, "Нужно число, например <code>1450</code>:")
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
    from ..premium import period, plans, refresh_rate, usd_rate

    await refresh_rate(session)
    rate = usd_rate()
    own = bool(settings.get("premium_usd"))
    plan_lines = "\n".join(
        f"• {period(m)}: {num(usd)} $" + (f" = {money(usd * rate)}" if rate else "") for m, usd in plans()) or "не заданы"
    rate_txt = (f"{num(rate)} ₸ " + ("(свой)" if own else "(продажа USDT из «💱 Курсы»)")) if rate else "не задан"
    await show(
        target,
        "⭐ <b>Звёзды</b>\n\n"
        f"<b>Сетка цен</b> (за 1 звезду):\n{lines}\n\n"
        f"<b>Кнопки количества:</b> {h(presets)}\n"
        f"<b>Выдача звёзд:</b> {h(settings.get('sla_stars'))}\n"
        f"<b>Срок обмена:</b> {h(settings.get('sla_exchange'))}\n"
        f"<b>Передача подарков:</b> {h(settings.get('sla_gifts'))}\n\n"
        f"👑 <b>Telegram Premium</b>\n{plan_lines}\n"
        f"<b>Курс $:</b> {rate_txt}\n"
        f"<b>Подключение:</b> {h(settings.get('sla_premium'))}"
        + ("" if settings.is_set("star_tiers") else "\n\n⚠️ <b>Сейчас стоят цены по умолчанию.</b> Нажмите «Сетка цен» и задайте свои."),
        kb(
            [btn("✏️ Сетка цен", Adm(s="stars", a="tiers")), btn("✏️ Кнопки", Adm(s="stars", a="presets"))],
            [btn("⏱ Срок звёзд", Adm(s="stars", a="sla", v="sla_stars")),
             btn("⏱ Срок обмена", Adm(s="stars", a="sla", v="sla_exchange"))],
            [btn("⏱ Срок подарков", Adm(s="stars", a="sla", v="sla_gifts")),
             btn("⏱ Срок Premium", Adm(s="stars", a="sla", v="sla_premium"))],
            [btn("👑 Цены Premium", Adm(s="stars", a="prem")), btn("💵 Курс $", Adm(s="stars", a="prem_usd"))],
            [btn("📢 Пост: звёзды", Adm(s="stars", a="post_stars")), btn("📢 Пост: Premium", Adm(s="stars", a="post_prem"))],
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
    elif callback_data.a == "sla" and callback_data.v in ("sla_stars", "sla_exchange", "sla_gifts", "sla_premium"):
        await ask(cb, state, "sla", "⏱ Введите срок текстом, например «от 15 минут до 3 часов»:", back, key=callback_data.v)
    elif callback_data.a in ("post_stars", "post_prem"):
        from .channel import start_text_post

        if callback_data.a == "post_stars":
            text, ents = await posting.stars_post(cb.bot)
        else:
            text, ents = await posting.premium_post(cb.bot, session)
        await start_text_post(cb, state, session, text, ents, back, "👀 <b>Пост в канал</b>")
    elif callback_data.a == "prem":
        await ask(cb, state, "premium_plans",
                  "👑 Пришлите тарифы Premium: каждая строка «месяцев» и «цена в $».\n\n"
                  "Пример:\n<code>3 17\n6 32\n12 60</code>", back)
    elif callback_data.a == "prem_usd":
        await ask(cb, state, "set_num", "💵 По какому курсу считать доллар для Premium, в тенге? Например <code>500</code>.\n"
                  "<code>0</code>: брать курс продажи USDT из «💱 Курсы».", back, key="premium_usd")
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
        await say(ctx.target, "Не нашёл ни одной строки. Формат: <code>50 9.5</code>")
        return
    await ctx.state.clear()
    await settings.put(ctx.session, "star_tiers", sorted(tiers))
    await ctx.session.commit()
    await stars_view(ctx.target, ctx.session, Adm(s="stars"))


@op("star_presets")
async def op_presets(ctx: Ctx) -> None:
    values = sorted({int(x) for x in re.findall(r"\d+", ctx.text or "") if 0 < int(x) <= 1_000_000})
    if not values:
        await say(ctx.target, "Пришлите числа через пробел:")
        return
    await ctx.state.clear()
    await settings.put(ctx.session, "star_presets", values[:12])
    await ctx.session.commit()
    await stars_view(ctx.target, ctx.session, Adm(s="stars"))


@op("sla")
async def op_sla(ctx: Ctx) -> None:
    if not ctx.text:
        await say(ctx.target, "Введите текст:")
        return
    await ctx.state.clear()
    await settings.put(ctx.session, ctx.data["key"], ctx.text.strip()[:100])
    await ctx.session.commit()
    await stars_view(ctx.target, ctx.session, Adm(s="stars"))


@op("premium_plans")
async def op_premium_plans(ctx: Ctx) -> None:
    rows = []
    for line in (ctx.text or "").splitlines():
        parts = line.replace(",", ".").replace("$", " ").split()
        if len(parts) >= 2:
            try:
                m, usd = int(parts[0]), float(Decimal(parts[1]))
            except Exception:
                continue
            if 0 < m <= 60 and usd > 0:
                rows.append([m, usd])
    if not rows:
        await say(ctx.target, "Не нашёл ни одной строки. Формат: <code>3 17</code>")
        return
    await ctx.state.clear()
    await settings.put(ctx.session, "premium_plans", sorted(rows)[:6])
    await ctx.session.commit()
    await stars_view(ctx.target, ctx.session, Adm(s="stars"))


@op("rates_bulk")
async def op_rates_bulk(ctx: Ctx) -> None:
    """«USDT 440 500» по строке на валюту: обновить всё за раз."""
    rows = []
    for line in (ctx.text or "").splitlines():
        parts = line.replace(",", ".").split()
        if len(parts) < 2:
            continue
        code = re.sub(r"[^A-Za-z0-9]", "", parts[0]).upper()[:16]
        vals = []
        for raw in parts[1:3]:
            vals.append(None if raw in ("-", "—") else parse_number(raw))
        while len(vals) < 2:
            vals.append(None)
        if code and any(v is not None for v in vals):
            rows.append((code, vals[0], vals[1]))
    if not rows:
        await say(ctx.target, "Не нашёл ни одной строки. Формат: <code>USDT 440 500</code>")
        return
    await ctx.state.clear()
    existing = {r.code.upper(): r for r in (await ctx.session.execute(select(Rate))).scalars().all()}
    sort = max([r.sort for r in existing.values()] or [0])
    changed = []
    for code, buy, sell in rows:
        r = existing.get(code)
        if r is None:
            sort += 1
            r = Rate(code=code, sort=sort)
            ctx.session.add(r)
        if buy is not None:
            r.buy = buy
        if sell is not None:
            r.sell = sell
        r.is_active = True
        changed.append(f"{code}: {num(r.buy) if r.buy else '-'} / {num(r.sell) if r.sell else '-'}")
    await settings.put(ctx.session, "rates_day", settings.today())
    await ctx.session.commit()
    await show(ctx.target, "✅ <b>Курсы на сегодня обновлены</b>\n\n" + h("\n".join(changed))
               + "\n\nСайт и бот уже считают по ним (сайт в течение минуты).",
               kb([btn("📢 Отправить курсы", Adm(s="rates", a="post"), style="primary")],
                  [btn("◀️ Курсы", Adm(s="rates"))]))
