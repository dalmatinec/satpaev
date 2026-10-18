"""Настройки подписки на канал: режим, каналы, проверка прав бота."""

import re

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from ...cb import Adm
from ...services import settings, subscription
from ...ui import answer, btn, kb, say, show
from ...utils import h
from .common import Ctx, ask, op, screen

router = Router(name="admin_subs")

MODES = ["required", "recommend", "off"]
MODE_NAMES = {"required": "🔒 обязательная", "recommend": "💡 рекомендуемая", "off": "⚪ выключена"}


@screen("sub")
async def sub_view(target, session: AsyncSession, cbd: Adm) -> None:
    mode = subscription.mode()
    chans = subscription.channels()
    lines = [f"• {h(c.get('title') or c['chat'])} ({h(c['chat'])})" for c in chans] or ["нет каналов"]
    text = (
        "📢 <b>Подписка на канал</b>\n\n"
        f"Режим: <b>{MODE_NAMES[mode]}</b>\n"
        "🔒 обязательная: без подписки ботом не пользоваться\n"
        "💡 рекомендуемая: при /start предложим подписаться, раз в сутки\n\n"
        "<b>Каналы:</b>\n" + "\n".join(lines) +
        "\n\n<i>Бот должен быть админом каждого канала, иначе проверить подписку нельзя (тогда клиента пропустим).</i>"
    )
    rows = [[btn(f"Режим: {MODE_NAMES[mode]}", Adm(s="sub", a="mode"))]]
    for i, c in enumerate(chans):
        rows.append([btn(f"🗑 Убрать {c.get('title') or c['chat']}"[:60], Adm(s="sub", a="del", i=i))])
    rows.append([btn("➕ Добавить канал", Adm(s="sub", a="add")), btn("🔍 Проверить права", Adm(s="sub", a="check"))])
    rows.append([btn("🔘 Кнопки и вид", Adm(s="bt", a="scr", v="sub")), btn("✏️ Тексты", Adm(s="tx", a="grp", v="sub"))])
    rows.append([btn("◀️ Ещё", Adm(s="more"))])
    await show(target, text, kb(*rows))


@router.callback_query(Adm.filter(F.s == "sub"))
async def on_sub(cb: CallbackQuery, callback_data: Adm, session: AsyncSession, state: FSMContext) -> None:
    a = callback_data.a
    if a == "mode":
        mode = MODES[(MODES.index(subscription.mode()) + 1) % len(MODES)]
        await settings.put(session, "sub_mode", mode)
        await session.commit()
    elif a == "del":
        chans = subscription.channels()
        if 0 <= callback_data.i < len(chans):
            chans.pop(callback_data.i)
            await settings.put(session, "sub_channels", chans)
            await session.commit()
    elif a == "add":
        await ask(cb, state, "sub_add",
                  "➕ Пришлите канал:\n• публичный: <code>@channel</code> или <code>https://t.me/channel</code>\n"
                  "• приватный: <code>-100id https://t.me/+ссылка</code>\n\nСначала добавьте бота в канал админом.",
                  Adm(s="sub"))
        return
    elif a == "check":
        me = await cb.bot.me()
        report = []
        for c in subscription.channels():
            try:
                member = await cb.bot.get_chat_member(c["chat"], me.id)
                ok = member.status in ("administrator", "creator")
                report.append(f"{'✅' if ok else '⚠️'} {c.get('title') or c['chat']}: {'бот админ' if ok else 'бот не админ'}")
            except (TelegramBadRequest, TelegramForbiddenError) as e:
                report.append(f"❌ {c['chat']}: {e}")
        await show(cb, "🔍 <b>Проверка</b>\n\n" + h("\n".join(report) or "Каналов нет"),
                   kb([btn("◀️ Подписка", Adm(s="sub"))]))
        return
    await sub_view(cb, session, Adm(s="sub"))


@op("sub_add")
async def op_sub_add(ctx: Ctx) -> None:
    raw = (ctx.text or "").strip()
    chat, url = "", ""
    m = re.match(r"^(-100\d+)\s+(https://t\.me/\S+)$", raw)
    if m:
        chat, url = m.group(1), m.group(2)
    else:
        m = re.match(r"^(?:https?://)?(?:t\.me/|@)([A-Za-z][A-Za-z0-9_]{3,31})/?$", raw)
        if m:
            chat, url = "@" + m.group(1), f"https://t.me/{m.group(1)}"
    if not chat:
        await say(ctx.target, "Не понял. Пример: <code>@newssatbox</code>")
        return
    try:
        info = await ctx.bot.get_chat(chat)
        title = info.title or chat
    except (TelegramBadRequest, TelegramForbiddenError):
        await say(ctx.target, "Бот не видит этот канал. Добавьте бота в канал админом и пришлите ещё раз.")
        return
    chans = [c for c in subscription.channels() if c["chat"] != chat]
    chans.append({"chat": chat, "url": url, "title": title})
    await settings.put(ctx.session, "sub_channels", chans)
    await ctx.session.commit()
    await ctx.state.clear()
    await sub_view(ctx.target, ctx.session, Adm(s="sub"))
