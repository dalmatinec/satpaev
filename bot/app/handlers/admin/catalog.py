"""Каталоги: подарки, готовые юзеры, услуги, портфолио. Добавление пошаговым мастером."""

from decimal import Decimal

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...catalog import DEV_CATS, FIELD_NAMES, FIELDS, KIND_NAMES
from ...cb import Adm, AIn
from ...db.models import Item
from ...services import settings
from ...states import AdmSt
from ...ui import btn, kb, pager, show
from ...utils import clean_username, h, money, num, parse_number
from ..usernames import ready_price
from .common import Ctx, ask, op, screen

router = Router(name="admin_catalog")
PER_PAGE = 8


def _label(item: Item) -> str:
    mark = "" if item.is_active else "🙈 "
    if item.kind == "uname":
        price_ton, _ = ready_price(item)
        return f"{mark}@{item.title} · {num(item.cost_ton)} → {price_ton} TON"
    if item.kind == "gift":
        return f"{mark}{item.title} · {money(item.price)}"
    if item.kind == "service":
        return f"{mark}{DEV_CATS.get(item.category, '').split(' ')[0]} {item.title}"
    return f"{mark}{item.title}"


@screen("cat")
async def view(target, session: AsyncSession, cbd: Adm) -> None:
    if cbd.a == "card":
        await card(target, session, cbd.i)
        return
    kind = cbd.v if cbd.v in FIELDS else "gift"
    total = await session.scalar(select(func.count(Item.id)).where(Item.kind == kind)) or 0
    pages = max(1, (total + PER_PAGE - 1) // PER_PAGE)
    page = max(0, min(cbd.p, pages - 1))
    items = (await session.execute(
        select(Item).where(Item.kind == kind).order_by(Item.is_active.desc(), Item.sort, Item.id.desc())
        .offset(page * PER_PAGE).limit(PER_PAGE)
    )).scalars().all()
    b = InlineKeyboardBuilder()
    for it in items:
        b.row(btn(_label(it)[:64], Adm(s="cat", a="card", i=it.id, v=kind)))
    pager(b, page, pages, lambda p: Adm(s="cat", v=kind, p=p))
    b.row(btn("➕ Добавить", Adm(s="cat", a="add", v=kind)))
    if kind in ("service", "portfolio"):  # эти разделы лежат в «Ещё»
        b.row(btn("◀️ Ещё", Adm(s="more")))
    else:
        b.row(btn("⚙️ Админка", Adm(s="menu")))
    hint = ""
    if kind == "uname":
        hint = (f"\n\nНаценка по умолчанию: <b>x{num(settings.get('uname_markup'))}</b>. "
                f"Курс TON: <b>{money(settings.get('ton_kzt')) if settings.get('ton_kzt') else 'не задан'}</b> (меняется в «Курсы»).")
    await show(target, f"{KIND_NAMES[kind]}: <b>{total}</b>\n🙈 значит скрыто или продано.{hint}", b.as_markup())


async def card(target, session: AsyncSession, item_id: int) -> None:
    it = await session.get(Item, item_id)
    if not it:
        await show(target, "Позиция не найдена.", kb([btn("⚙️ Админка", Adm(s="menu"))]))
        return
    lines = [f"{KIND_NAMES[it.kind]} · #{it.id}", f"Статус: <b>{'показывается' if it.is_active else 'скрыто'}</b>", ""]
    for field, _, ftype, _ in FIELDS[it.kind]:
        value = getattr(it, field)
        if ftype == "photo":
            value = "есть" if value else "нет"
        elif field == "category":
            value = DEV_CATS.get(value, value)
        elif field == "price":
            value = money(value) if value is not None else "нет"
        elif field in ("cost_ton", "markup"):
            value = num(value) if value is not None else "по умолчанию" if field == "markup" else "нет"
        lines.append(f"{FIELD_NAMES[field]}: <b>{h(value) if value not in (None, '') else 'нет'}</b>")
    if it.kind == "uname":
        price_ton, price_kzt = ready_price(it)
        lines.append(f"\nЦена для клиента: <b>{price_ton} TON</b>" + (f" (≈ {money(price_kzt)})" if price_kzt else ""))
    b = InlineKeyboardBuilder()
    for field, _, _, _ in FIELDS[it.kind]:
        b.button(text=f"✏️ {FIELD_NAMES[field]}", callback_data=Adm(s="cat", a="edit", i=it.id, v=field))
    b.adjust(2)
    b.row(btn("🙈 Скрыть" if it.is_active else "👁 Показать", Adm(s="cat", a="toggle", i=it.id)),
          btn("🔼 Выше", Adm(s="cat", a="up", i=it.id)))
    b.row(btn("🗑 Удалить", Adm(s="cat", a="del", i=it.id)))
    b.row(btn("◀️ К списку", Adm(s="cat", v=it.kind)))
    await show(target, "\n".join(lines), b.as_markup(), photo=it.photo or None)


# ---------- мастер добавления ----------


def _validate(ftype: str, message: Message | None, text: str | None) -> tuple[bool, object, str]:
    if ftype == "photo":
        if message and message.photo:
            return True, message.photo[-1].file_id, ""
        return False, None, "Пришлите фото (как картинку, не файлом)."
    if ftype == "number":
        value = parse_number(text)
        return (True, value, "") if value is not None else (False, None, "Нужно число, например <code>1500</code>.")
    if ftype == "username":
        value = clean_username(text)
        return (True, value, "") if value else (False, None, "Неверный юзернейм. Латиница, цифры, «_», от 4 символов.")
    if ftype == "url":
        value = (text or "").strip()
        if value.startswith("t.me/"):
            value = "https://" + value
        if value.startswith(("http://", "https://")):
            return True, value[:512], ""
        return False, None, "Нужна ссылка, начинающаяся с https:// или t.me/"
    if ftype == "choice":
        value = (text or "").strip()
        if value in DEV_CATS:
            return True, value, ""
        return False, None, "Выберите категорию кнопкой."
    value = (text or "").strip()
    if not value:
        return False, None, "Пришлите текст."
    return True, value[:2000], ""


def _choice_kb(skip: bool, back: Adm):
    b = InlineKeyboardBuilder()
    for key, name in DEV_CATS.items():
        b.button(text=name, callback_data=AIn(a="wz_choice", v=key))
    b.adjust(2)
    if skip:
        b.row(btn("➡️ Пропустить", AIn(a="wz_skip")))
    b.row(btn("◀️ Отмена", back))
    return b.as_markup()


async def _wizard_prompt(target, state: FSMContext) -> None:
    data = await state.get_data()
    kind, step = data["kind"], data["step"]
    field, question, ftype, optional = FIELDS[kind][step]
    back = Adm(s="cat", v=kind)
    head = f"➕ <b>{KIND_NAMES[kind]}</b> · шаг {step + 1} из {len(FIELDS[kind])}\n\n{question}"
    if optional:
        head += "\n\n<i>Можно пропустить.</i>"
    if ftype == "choice":
        await show(target, head, _choice_kb(optional, back))
        return
    rows = []
    if optional:
        rows.append([btn("➡️ Пропустить", AIn(a="wz_skip"))])
    rows.append([btn("◀️ Отмена", back)])
    await show(target, head, kb(*rows))


async def _wizard_next(target, state: FSMContext, session: AsyncSession, value) -> None:
    data = await state.get_data()
    kind, step = data["kind"], data["step"]
    field = FIELDS[kind][step][0]
    values = dict(data.get("values") or {})
    if value is not None:
        values[field] = str(value) if isinstance(value, Decimal) else value
    step += 1
    if step < len(FIELDS[kind]):
        await state.update_data(step=step, values=values)
        await _wizard_prompt(target, state)
        return
    await state.clear()
    sort = (await session.scalar(select(func.max(Item.sort)).where(Item.kind == kind))) or 0
    item = Item(kind=kind, sort=sort + 1)
    for key, val in values.items():
        if key in ("price", "cost_ton", "markup"):
            val = Decimal(str(val))
        setattr(item, key, val)
    session.add(item)
    await session.commit()
    await card(target, session, item.id)


@router.callback_query(Adm.filter((F.s == "cat") & (F.a == "add")))
async def wizard_start(cb: CallbackQuery, callback_data: Adm, state: FSMContext) -> None:
    kind = callback_data.v if callback_data.v in FIELDS else "gift"
    await state.set_state(AdmSt.wizard)
    await state.set_data({"kind": kind, "step": 0, "values": {}})
    await _wizard_prompt(cb, state)


@router.message(AdmSt.wizard)
async def wizard_input(message: Message, state: FSMContext, session: AsyncSession) -> None:
    data = await state.get_data()
    _, _, ftype, _ = FIELDS[data["kind"]][data["step"]]
    ok, value, error = _validate(ftype, message, message.text or message.caption)
    if not ok:
        await message.answer(error)
        return
    await _wizard_next(message, state, session, value)


@router.callback_query(AdmSt.wizard, AIn.filter(F.a == "wz_skip"))
async def wizard_skip(cb: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    data = await state.get_data()
    if not FIELDS[data["kind"]][data["step"]][3]:
        await cb.answer("Это поле обязательное", show_alert=True)
        return
    await _wizard_next(cb, state, session, None)


@router.callback_query(AdmSt.wizard, AIn.filter(F.a == "wz_choice"))
async def wizard_choice(cb: CallbackQuery, callback_data: AIn, state: FSMContext, session: AsyncSession) -> None:
    await _wizard_next(cb, state, session, callback_data.v)


# ---------- действия с позицией ----------


@router.callback_query(Adm.filter(F.s == "cat"))
async def on_catalog(cb: CallbackQuery, callback_data: Adm, session: AsyncSession, state: FSMContext) -> None:
    a = callback_data.a
    if a in ("", "card"):
        await view(cb, session, callback_data)
        return
    it = await session.get(Item, callback_data.i)
    if not it:
        await view(cb, session, Adm(s="cat", v=callback_data.v))
        return
    back = Adm(s="cat", a="card", i=it.id)
    if a == "edit" and callback_data.v in FIELD_NAMES:
        spec = next((f for f in FIELDS[it.kind] if f[0] == callback_data.v), None)
        if not spec:
            await card(cb, session, it.id)
            return
        field, question, ftype, optional = spec
        if ftype == "choice":
            await state.set_state(AdmSt.input)
            await state.set_data({"op": "item_field", "back": back.pack(), "item_id": it.id, "field": field})
            b = InlineKeyboardBuilder()
            for key, name in DEV_CATS.items():
                b.button(text=name, callback_data=AIn(a="item_choice", v=key))
            b.adjust(2)
            b.row(btn("◀️ Отмена", back))
            await show(cb, question, b.as_markup())
            return
        await ask(cb, state, "item_field", f"✏️ {question}", back, skip=optional, item_id=it.id, field=field)
    elif a == "toggle":
        it.is_active = not it.is_active
        await session.commit()
        await card(cb, session, it.id)
    elif a == "up":
        items = (await session.execute(select(Item).where(Item.kind == it.kind).order_by(Item.sort, Item.id))).scalars().all()
        ids = [x.id for x in items]
        i = ids.index(it.id)
        if i > 0:
            ids[i - 1], ids[i] = ids[i], ids[i - 1]
        by_id = {x.id: x for x in items}
        for n, x_id in enumerate(ids):
            by_id[x_id].sort = n
        await session.commit()
        await cb.answer("Поднято выше")
        await card(cb, session, it.id)
    elif a == "del":
        await show(cb, "Удалить позицию насовсем?", kb([btn("🗑 Да, удалить", Adm(s="cat", a="del_ok", i=it.id))],
                                                      [btn("◀️ Нет", back)]))
    elif a == "del_ok":
        kind = it.kind
        await session.delete(it)
        await session.commit()
        await view(cb, session, Adm(s="cat", v=kind))


@op("item_field")
async def op_item_field(ctx: Ctx) -> None:
    it = await ctx.session.get(Item, int(ctx.data["item_id"]))
    if not it:
        await ctx.back()
        return
    field = ctx.data["field"]
    spec = next(f for f in FIELDS[it.kind] if f[0] == field)
    if ctx.message is None:  # пропуск = очистить поле
        value = None if field in ("price", "cost_ton", "markup") else ""
    else:
        ok, value, error = _validate(spec[2], ctx.message, ctx.text)
        if not ok:
            await ctx.target.answer(error)
            return
    setattr(it, field, value)
    await ctx.session.commit()
    await ctx.state.clear()
    await card(ctx.target, ctx.session, it.id)


@router.callback_query(AdmSt.input, AIn.filter(F.a == "item_choice"))
async def item_choice(cb: CallbackQuery, callback_data: AIn, state: FSMContext, session: AsyncSession) -> None:
    data = await state.get_data()
    it = await session.get(Item, int(data.get("item_id") or 0))
    await state.clear()
    if it and callback_data.v in DEV_CATS:
        it.category = callback_data.v
        await session.commit()
        await card(cb, session, it.id)
        return
    await view(cb, session, Adm(s="cat", v="service"))
