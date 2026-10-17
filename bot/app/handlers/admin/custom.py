"""Оформление: тексты, кнопки и раскладка главного меню, картинки разделов."""

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from ...cb import Adm
from ...services import media, settings
from ...texts import BUTTON_GROUPS, BUTTONS, GROUPS, IMAGES, MENU_KEYS, TEXTS, strip_html
from ...ui import answer, btn, kb, show
from ...utils import h
from .common import Ctx, ask, op, screen

router = Router(name="admin_custom")

STYLES = ["", "primary", "success", "danger"]
STYLE_NAMES = {"": "обычный", "primary": "🔵 синий", "success": "🟢 зелёный", "danger": "🔴 красный"}


# ======================= ТЕКСТЫ =======================

@screen("tx")
async def tx_view(target, session: AsyncSession, cbd: Adm) -> None:
    if cbd.a == "grp" and cbd.v in GROUPS:
        b = InlineKeyboardBuilder()
        for key, spec in TEXTS.items():
            if spec.group == cbd.v:
                mark = "✏️ " if settings.text_is_custom(key) else ""
                b.row(btn(f"{mark}{spec.title}", Adm(s="tx", a="card", v=key)))
        b.row(btn("◀️ Разделы", Adm(s="tx")))
        await show(target, f"✏️ <b>Тексты</b> · {GROUPS[cbd.v]}\n\n✏️ отмечены изменённые вами.", b.as_markup())
        return
    if cbd.a == "card" and cbd.v in TEXTS:
        await tx_card(target, cbd.v)
        return
    custom = len(settings.get("texts") or {})
    b = InlineKeyboardBuilder()
    for key, name in GROUPS.items():
        b.button(text=name, callback_data=Adm(s="tx", a="grp", v=key))
    b.adjust(2)
    b.row(btn("◀️ Ещё", Adm(s="more")))
    await show(
        target,
        "✏️ <b>Тексты бота</b>\n\nЗдесь меняется любой текст, который видит клиент. "
        "Пишите прямо в Telegram: жирный, ссылки и премиум эмодзи сохранятся.\n\n"
        f"Изменено текстов: <b>{custom}</b>",
        b.as_markup(),
    )


async def tx_card(target, key: str) -> None:
    spec = TEXTS[key]
    custom = settings.text_is_custom(key)
    current = (settings.get("texts") or {}).get(key) or spec.default
    variables = ", ".join("{" + v + "}" for v in spec.vars) or "нет"
    head = (
        f"✏️ <b>{h(spec.title)}</b> · {GROUPS[spec.group]}\n"
        f"Переменные: <code>{h(variables)}</code>\n"
        f"Состояние: <b>{'изменён' if custom else 'стандартный'}</b>"
        + ("\n<i>Это всплывающее уведомление: без форматирования, до 200 символов.</i>" if spec.plain else "")
        + "\n\n➖➖➖➖➖➖\n"
    )
    rows = [[btn("✏️ Изменить", Adm(s="tx", a="edit", v=key))]]
    if custom:
        rows.append([btn("♻️ Вернуть стандартный", Adm(s="tx", a="reset", v=key))])
    rows.append([btn("◀️ Назад", Adm(s="tx", a="grp", v=spec.group))])
    await show(target, head + current, kb(*rows))


@router.callback_query(Adm.filter(F.s == "tx"))
async def on_tx(cb: CallbackQuery, callback_data: Adm, session: AsyncSession, state: FSMContext) -> None:
    key = callback_data.v
    if callback_data.a == "edit" and key in TEXTS:
        spec = TEXTS[key]
        variables = ", ".join("{" + v + "}" for v in spec.vars)
        hint = f"\n\nМожно использовать: <code>{h(variables)}</code>" if variables else ""
        await ask(cb, state, "tx_edit",
                  f"✏️ Пришлите новый текст «{h(spec.title)}» одним сообщением.{hint}",
                  Adm(s="tx", a="card", v=key), key=key)
    elif callback_data.a == "reset" and key in TEXTS:
        await settings.set_text(session, key, None)
        await session.commit()
        await answer(cb, "Вернул стандартный текст")
        await tx_card(cb, key)
    else:
        await tx_view(cb, session, callback_data)


@op("tx_edit")
async def op_tx_edit(ctx: Ctx) -> None:
    key = ctx.data["key"]
    if ctx.message is None or not (ctx.message.text or ctx.message.caption):
        await ctx.target.answer("Пришлите текст сообщением.")
        return
    html = ctx.message.html_text
    if TEXTS[key].plain:
        html = h(strip_html(html))[:200]
    if len(html) > 3800:
        await ctx.target.answer("Слишком длинный текст, сократите до ~3500 символов.")
        return
    await settings.set_text(ctx.session, key, html)
    await ctx.session.commit()
    await ctx.state.clear()
    missing = [v for v in TEXTS[key].vars if "{" + v + "}" not in html and v not in ("brand", "name")]
    if missing:
        await ctx.target.answer("⚠️ В тексте нет " + ", ".join("{" + v + "}" for v in missing) +
                                ": эти значения клиент не увидит. Если так задумано, всё в порядке.")
    await tx_card(ctx.target, key)


# ======================= КНОПКИ И МЕНЮ =======================

def _layout_kb() -> list:
    rows = []
    for row in settings.menu_layout():
        line = []
        for key in row:
            spec = settings.button(key)
            line.append(btn(spec["text"], Adm(s="bt", a="card", v=key), icon=spec["icon"] or None, style=spec["style"] or None))
        rows.append(line)
    return rows


def _hidden() -> list[str]:
    shown = {k for row in settings.menu_layout() for k in row}
    return [k for k in MENU_KEYS if k not in shown]


@screen("bt")
async def bt_view(target, session: AsyncSession, cbd: Adm) -> None:
    if cbd.a == "menu":
        await menu_builder(target)
        return
    if cbd.a == "grp" and cbd.v in BUTTON_GROUPS:
        b = InlineKeyboardBuilder()
        for key, (group, _) in BUTTONS.items():
            if group == cbd.v:
                spec = settings.button(key)
                b.row(btn(spec["text"][:60], Adm(s="bt", a="card", v=key)))
        b.row(btn("◀️ Кнопки", Adm(s="bt")))
        await show(target, f"🔘 <b>{BUTTON_GROUPS[cbd.v]}</b>\n\nНажмите кнопку, чтобы изменить её.", b.as_markup())
        return
    if cbd.a == "card" and cbd.v in BUTTONS:
        await bt_card(target, cbd.v)
        return
    await show(target, "🔘 <b>Кнопки и меню</b>\n\n"
                       "Меняйте текст кнопок, премиум иконки, цвет и порядок кнопок главного меню.", kb(
        [btn("🏠 Конструктор главного меню", Adm(s="bt", a="menu"))],
        [btn("🧩 Общие кнопки", Adm(s="bt", a="grp", v="common")), btn("🛍 Кнопки разделов", Adm(s="bt", a="grp", v="shop"))],
        [btn("◀️ Ещё", Adm(s="more"))],
    ))


async def menu_builder(target) -> None:
    rows = _layout_kb()
    hidden = _hidden()
    if hidden:
        rows.append([btn("➖ скрытые кнопки ➖", Adm(s="bt", a="menu"))])
        for key in hidden:
            rows.append([btn(f"👁 Показать «{strip_html(settings.button(key)['text'])}»", Adm(s="bt", a="unhide", v=key))])
    rows.append([btn("📐 Раскладка текстом", Adm(s="bt", a="layout")), btn("♻️ Сбросить", Adm(s="bt", a="layout_reset"))])
    rows.append([btn("◀️ Кнопки", Adm(s="bt"))])
    await show(
        target,
        "🏠 <b>Конструктор главного меню</b>\n\n"
        "Сверху меню выглядит так же, как у клиента. Нажмите на кнопку, чтобы переименовать, "
        "поставить премиум иконку, цвет или передвинуть её.",
        kb(*rows),
    )


async def bt_card(target, key: str) -> None:
    spec = settings.button(key)
    default = BUTTONS[key][1]
    in_menu = key in MENU_KEYS
    text = (
        f"🔘 <b>Кнопка</b>\n\n"
        f"Текст: <b>{h(spec['text'])}</b>\n"
        f"Стандартный: {h(default)}\n"
        f"Премиум иконка: <b>{'есть' if spec['icon'] else 'нет'}</b>\n"
        f"Цвет: <b>{STYLE_NAMES.get(spec['style'], spec['style'])}</b>\n\n"
        "Предпросмотр 👇"
    )
    rows = [[btn(spec["text"], Adm(s="bt", a="card", v=key), icon=spec["icon"] or None, style=spec["style"] or None)]]
    rows.append([btn("✏️ Текст", Adm(s="bt", a="text", v=key)), btn("😀 Иконка", Adm(s="bt", a="icon", v=key)),
                 btn("🎨 Цвет", Adm(s="bt", a="style", v=key))])
    if in_menu:
        shown = any(key in row for row in settings.menu_layout())
        if shown:
            rows.append([btn("⬅️", Adm(s="bt", a="mv_l", v=key)), btn("⬆️", Adm(s="bt", a="mv_u", v=key)),
                         btn("⬇️", Adm(s="bt", a="mv_d", v=key)), btn("➡️", Adm(s="bt", a="mv_r", v=key))])
            rows.append([btn("↕️ Отдельной строкой", Adm(s="bt", a="solo", v=key)), btn("🙈 Скрыть", Adm(s="bt", a="hide", v=key))])
        else:
            rows.append([btn("👁 Показать в меню", Adm(s="bt", a="unhide", v=key))])
    rows.append([btn("♻️ Сбросить кнопку", Adm(s="bt", a="reset", v=key))])
    back = Adm(s="bt", a="menu") if in_menu else Adm(s="bt", a="grp", v=BUTTONS[key][0])
    rows.append([btn("◀️ Назад", back)])
    await show(target, text, kb(*rows))


def _find(layout: list[list[str]], key: str) -> tuple[int, int]:
    for r, row in enumerate(layout):
        if key in row:
            return r, row.index(key)
    return -1, -1


def _move(layout: list[list[str]], key: str, action: str) -> list[list[str]]:
    layout = [list(r) for r in layout]
    r, c = _find(layout, key)
    if r < 0:
        if action == "unhide":
            layout.append([key])
        return layout
    row = layout[r]
    if action == "mv_l" and c > 0:
        row[c - 1], row[c] = row[c], row[c - 1]
    elif action == "mv_r" and c < len(row) - 1:
        row[c + 1], row[c] = row[c], row[c + 1]
    elif action == "mv_u":
        row.pop(c)
        if r > 0 and len(layout[r - 1]) < 8:
            layout[r - 1].append(key)
        else:
            layout.insert(r, [key])
            r += 1
    elif action == "mv_d":
        row.pop(c)
        if r + 1 < len(layout) and len(layout[r + 1]) < 8:
            layout[r + 1].insert(0, key)
        else:
            layout.insert(r + 1, [key])
    elif action == "solo" and len(row) > 1:
        row.pop(c)
        layout.insert(r + 1, [key])
    elif action == "hide":
        row.pop(c)
    return [x for x in layout if x]


@router.callback_query(Adm.filter(F.s == "bt"))
async def on_bt(cb: CallbackQuery, callback_data: Adm, session: AsyncSession, state: FSMContext) -> None:
    a, key = callback_data.a, callback_data.v
    if a in ("mv_l", "mv_r", "mv_u", "mv_d", "solo", "hide", "unhide") and key in MENU_KEYS:
        await settings.set_menu_layout(session, _move(settings.menu_layout(), key, a))
        await session.commit()
        if a in ("hide", "unhide"):
            await menu_builder(cb)
        else:
            await bt_card(cb, key)
    elif a == "layout_reset":
        await settings.set_menu_layout(session, None)
        await session.commit()
        await answer(cb, "Раскладка как по умолчанию")
        await menu_builder(cb)
    elif a == "layout":
        legend = "\n".join(f"<code>{k}</code>: {h(strip_html(settings.button(k)['text']))}" for k in MENU_KEYS)
        current = "\n".join(" ".join(r) for r in settings.menu_layout())
        await ask(cb, state, "bt_layout",
                  "📐 <b>Раскладка текстом</b>\n\nКаждая строка сообщения = ряд кнопок, коды через пробел. "
                  "Не указанные кнопки будут скрыты.\n\n"
                  f"{legend}\n\nСейчас:\n<code>{h(current)}</code>",
                  Adm(s="bt", a="menu"))
    elif a == "text" and key in BUTTONS:
        hint = " Можно использовать переменные, как в стандартном тексте." if "{" in BUTTONS[key][1] else ""
        await ask(cb, state, "bt_text", f"✏️ Пришлите новый текст кнопки (до 60 символов).{hint}\n"
                                        "Эмодзи в начале можно оставить обычным, а премиум иконку поставить отдельно.",
                  Adm(s="bt", a="card", v=key), key=key)
    elif a == "icon" and key in BUTTONS:
        await ask(cb, state, "bt_icon",
                  "😀 Пришлите одно премиум эмодзи, оно встанет иконкой перед текстом кнопки.\n"
                  "«Пропустить» уберёт иконку.\n\n<i>Работает, пока у владельца бота есть Telegram Premium.</i>",
                  Adm(s="bt", a="card", v=key), skip=True, key=key)
    elif a == "style" and key in BUTTONS:
        current = settings.button(key)["style"]
        nxt = STYLES[(STYLES.index(current) + 1) % len(STYLES)] if current in STYLES else ""
        await settings.set_button(session, key, style=nxt)
        await session.commit()
        await bt_card(cb, key)
    elif a == "reset" and key in BUTTONS:
        await settings.set_button(session, key, text="", icon="", style="")
        await session.commit()
        await bt_card(cb, key)
    else:
        await bt_view(cb, session, callback_data)


@op("bt_text")
async def op_bt_text(ctx: Ctx) -> None:
    text = strip_html(ctx.text or "").strip()
    if not text:
        await ctx.target.answer("Пришлите текст:")
        return
    await settings.set_button(ctx.session, ctx.data["key"], text=text[:60])
    await ctx.session.commit()
    await ctx.state.clear()
    await bt_card(ctx.target, ctx.data["key"])


@op("bt_icon")
async def op_bt_icon(ctx: Ctx) -> None:
    icon = ""
    if ctx.message is not None:
        ents = ctx.message.entities or ctx.message.caption_entities or []
        icon = next((e.custom_emoji_id for e in ents if e.type == "custom_emoji"), "") or ""
        if not icon:
            await ctx.target.answer("Это не премиум эмодзи. Пришлите эмодзи из премиум набора:")
            return
    await settings.set_button(ctx.session, ctx.data["key"], icon=icon)
    await ctx.session.commit()
    await ctx.state.clear()
    await bt_card(ctx.target, ctx.data["key"])


@op("bt_layout")
async def op_bt_layout(ctx: Ctx) -> None:
    rows, seen, unknown = [], set(), []
    for line in (ctx.text or "").splitlines():
        row = []
        for word in line.replace(",", " ").split():
            key = word.strip().lower()
            if key in MENU_KEYS and key not in seen and len(row) < 8:
                row.append(key)
                seen.add(key)
            elif key not in MENU_KEYS:
                unknown.append(word)
        if row:
            rows.append(row)
    if not rows:
        await ctx.target.answer("Не нашёл ни одного кода кнопки. Пример:\n<code>stars gifts\nun ex\ndev</code>")
        return
    await settings.set_menu_layout(ctx.session, rows)
    await ctx.session.commit()
    await ctx.state.clear()
    if unknown:
        await ctx.target.answer("Пропустил неизвестное: " + h(", ".join(unknown[:10])))
    await menu_builder(ctx.target)


# ======================= КАРТИНКИ =======================

@screen("img")
async def img_view(target, session: AsyncSession, cbd: Adm) -> None:
    if cbd.a == "card" and cbd.v in IMAGES:
        key = cbd.v
        file_id = media.photo(key)
        rows = [[btn("📤 Загрузить новую", Adm(s="img", a="set", v=key))]]
        if file_id:
            rows.append([btn("🗑 Убрать картинку", Adm(s="img", a="del", v=key))])
        rows.append([btn("◀️ Картинки", Adm(s="img"))])
        text = (f"🖼 <b>{IMAGES[key]}</b>\n\n" +
                ("Сейчас стоит эта картинка. Она хранится на сервере в базе и попадает в бэкап."
                 if file_id else "Картинки нет, раздел показывается текстом."))
        await show(target, text, kb(*rows), photo=file_id)
        return
    b = InlineKeyboardBuilder()
    for key, name in IMAGES.items():
        mark = "✅ " if media.photo(key) else ""
        b.button(text=mark + name, callback_data=Adm(s="img", a="card", v=key))
    b.adjust(2)
    b.row(btn("◀️ Ещё", Adm(s="more")))
    await show(target, "🖼 <b>Картинки разделов</b>\n\nКартинка показывается над текстом раздела. "
                       "✅ значит картинка стоит.\n\n<i>Если текст раздела длиннее 1024 символов, "
                       "Telegram не даст поставить его под картинку, тогда раздел покажется без неё.</i>",
               b.as_markup())


@router.callback_query(Adm.filter(F.s == "img"))
async def on_img(cb: CallbackQuery, callback_data: Adm, session: AsyncSession, state: FSMContext) -> None:
    key = callback_data.v
    if callback_data.a == "set" and key in IMAGES:
        await ask(cb, state, "img_set", f"📤 Пришлите картинку для раздела «{IMAGES[key]}» (как фото, не файлом).",
                  Adm(s="img", a="card", v=key), key=key)
    elif callback_data.a == "del" and key in IMAGES:
        await media.remove(session, key)
        await img_view(cb, session, Adm(s="img", a="card", v=key))
    else:
        await img_view(cb, session, callback_data)


@op("img_set")
async def op_img_set(ctx: Ctx) -> None:
    if ctx.message is None or not ctx.message.photo:
        await ctx.target.answer("Пришлите именно фото (сжатой картинкой).")
        return
    await media.save(ctx.session, ctx.bot, ctx.data["key"], ctx.message.photo[-1].file_id)
    await ctx.state.clear()
    await img_view(ctx.target, ctx.session, Adm(s="img", a="card", v=ctx.data["key"]))

