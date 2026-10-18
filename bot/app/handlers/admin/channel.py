"""Посты: в каналы от вашего аккаунта (постер), в канал через бота и во все чаты с ботом."""

import asyncio
import os

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...cb import Adm, AIn
from ...config import config
from ...db.models import BotChat, Post, PosterChannel, User
from ...services import posting, settings
from ...states import AdmSt
from ...ui import answer, btn, kb, show
from ...utils import entities_from_store, entities_to_store, fdate, h, strip_custom_emoji
from .common import screen

router = Router(name="admin_channel")

POST_ICONS = {"pending": "⏳", "sending": "📤", "sent": "✅", "failed": "⚠️", "unknown": "❔"}
GROUP_TYPES = ("group", "supergroup")


async def _counts(session: AsyncSession) -> tuple[int, int]:
    acc = await session.scalar(select(func.count(PosterChannel.id))) or 0
    chats = await session.scalar(
        select(func.count(BotChat.id)).where(BotChat.active.is_(True), BotChat.type.in_(GROUP_TYPES))) or 0
    return acc, chats


@screen("ch")
async def view(target, session: AsyncSession, cbd: Adm) -> None:
    if cbd.a == "queue":
        await queue(target, session)
        return
    if cbd.a == "mine":
        await my_channels(target, session)
        return
    if cbd.a == "chats":
        await bot_chats(target, session)
        return
    _, state_txt, info = await posting.poster_status(session)
    counts = dict((await session.execute(select(Post.status, func.count(Post.id)).group_by(Post.status))).all())
    acc, chats = await _counts(session)
    mode = settings.get("post_mode")
    mode_txt = "👤 от вашего аккаунта" if mode == "account" else "🤖 от бота"
    text = (
        "📢 <b>Посты</b>\n\n"
        f"Основной канал: <code>{h(config.channel_id or 'не задан в .env')}</code>\n"
        f"Курсы и отзывы публикуются: <b>{mode_txt}</b>\n"
        f"Аккаунт для постинга: {state_txt}" + (f" · {h(info)}" if info else "") + "\n"
        f"Каналов аккаунта: <b>{acc}</b> · чатов с ботом: <b>{chats}</b>\n\n"
        f"Очередь: ⏳ {counts.get('pending', 0)} · ✅ {counts.get('sent', 0)} · "
        f"⚠️ {counts.get('failed', 0) + counts.get('unknown', 0)}"
    )
    if not config.poster_enabled:
        text += ("\n\n<i>Чтобы постить от своего аккаунта с премиум эмодзи, укажите TG_API_ID и TG_API_HASH "
                 "в .env и войдите командой из README.</i>")
    await show(target, text, kb(
        [btn("✍️ Новый пост", Adm(s="ch", a="new"))],
        [btn("💱 Отправить курсы", Adm(s="rates", a="post")), btn("📄 Очередь", Adm(s="ch", a="queue"))],
        [btn(f"👤 Мои каналы ({acc})", Adm(s="ch", a="mine")), btn(f"💬 Чаты с ботом ({chats})", Adm(s="ch", a="chats"))],
        [btn("🔁 Курсы и отзывы: аккаунт или бот", Adm(s="ch", a="mode"))],
        [btn("⚙️ Админка", Adm(s="menu"))],
    ))


async def my_channels(target, session: AsyncSession) -> None:
    rows = (await session.execute(select(PosterChannel).order_by(PosterChannel.title).limit(50))).scalars().all()
    lines = [f"• {h(c.title)}" + (f" (@{h(c.username)})" if c.username else "") for c in rows]
    updated = fdate(rows[0].updated_at) if rows else "ещё не обновлялся"
    await show(
        target,
        "👤 <b>Каналы вашего аккаунта</b>\n\nСюда попадают каналы, где ваш аккаунт может публиковать посты. "
        f"Список обновляет постер раз в 6 часов.\nОбновлён: {updated}\n\n" + ("\n".join(lines) or "Пусто"),
        kb([btn("🔄 Обновить сейчас", Adm(s="ch", a="refresh"))], [btn("◀️ Посты", Adm(s="ch"))]),
    )


async def bot_chats(target, session: AsyncSession) -> None:
    rows = (await session.execute(
        select(BotChat).where(BotChat.active.is_(True)).order_by(BotChat.type, BotChat.title).limit(60)
    )).scalars().all()
    lines = [("📢 " if c.type == "channel" else "💬 ") + h(c.title or str(c.id)) for c in rows]
    await show(
        target,
        "💬 <b>Чаты с ботом</b>\n\nГруппы, куда добавлен бот. Пост уходит туда копией: без пометки «переслано», "
        "с фото, видео, кнопками форматирования и премиум эмодзи.\n\nЧтобы добавить чат, добавьте бота в группу, "
        "он появится здесь сам.\n\n" + ("\n".join(lines) or "Пока нет ни одного чата"),
        kb([btn("◀️ Посты", Adm(s="ch"))]),
    )


async def queue(target, session: AsyncSession) -> None:
    posts = (await session.execute(select(Post).order_by(Post.id.desc()).limit(10))).scalars().all()
    lines = []
    b = InlineKeyboardBuilder()
    for p in posts:
        preview = (p.text or p.media_kind or "медиа").replace("\n", " ")[:40]
        lines.append(f"{POST_ICONS.get(p.status, '•')} #{p.id} · {fdate(p.created_at)} · {h(preview)}"
                     + (f"\n   <i>{h(p.error[:120])}</i>" if p.error and p.status != "sent" else ""))
        if p.status in ("failed", "unknown"):
            b.button(text=f"🔁 Повторить #{p.id}", callback_data=Adm(s="ch", a="retry", i=p.id))
    b.adjust(2)
    b.row(btn("◀️ Посты", Adm(s="ch")))
    await show(target, "📄 <b>Последние посты</b>\n\n" + ("\n".join(lines) or "Постов ещё не было.") +
               "\n\n❔ значит отправка прервалась: проверьте канал, прежде чем повторять.", b.as_markup())


@router.callback_query(Adm.filter(F.s == "ch"))
async def on_channel(cb: CallbackQuery, callback_data: Adm, session: AsyncSession, state: FSMContext) -> None:
    a = callback_data.a
    if a == "new":
        await state.set_state(AdmSt.post)
        await show(cb, "✍️ Пришлите пост одним сообщением: текст, фото, видео, гиф или файл с подписью.\n\n"
                       "Премиум эмодзи и форматирование сохранятся. Дальше выберете, куда публиковать.",
                   kb([btn("◀️ Отмена", Adm(s="ch"))]))
    elif a == "mode":
        if settings.get("post_mode") == "account":
            await settings.put(session, "post_mode", "bot")
        elif config.poster_enabled:
            await settings.put(session, "post_mode", "account")
        else:
            await answer(cb, "Для публикации от аккаунта нужны TG_API_ID и TG_API_HASH в .env", alert=True)
            return
        await session.commit()
        await view(cb, session, Adm(s="ch"))
    elif a == "refresh":
        await posting.request_refresh(session)
        await answer(cb, "Постер обновит список в течение минуты", alert=True)
        await my_channels(cb, session)
    elif a == "retry":
        post = await session.get(Post, callback_data.i)
        if post and post.status in ("failed", "unknown"):
            if post.mode == "account":
                post.status = "pending"
                post.error = ""
                await session.commit()
                await answer(cb, "Пост снова в очереди")
            else:
                await session.delete(post)
                await session.commit()
                ok, info = await posting.publish(session, cb.bot, post.text, post.entities, kind=post.kind, target=post.target)
                await answer(cb, info[:190], alert=not ok)
        await queue(cb, session)
    else:
        await view(cb, session, callback_data)


# ---------------- новый пост ----------------

async def _options(session: AsyncSession, bot=None) -> list[dict]:
    opts: list[dict] = []
    main = (config.channel_id or "").lstrip("@").lower()
    if config.poster_enabled:
        chans = (await session.execute(select(PosterChannel).order_by(PosterChannel.title).limit(40))).scalars().all()
        for c in chans:
            is_main = main and (main == (c.username or "").lower() or main == str(c.id))
            opts.append({"type": "acc", "target": str(c.id), "title": f"👤 {c.title}", "on": bool(is_main)})
        if not chans and config.channel_id:
            opts.append({"type": "acc", "target": config.channel_id, "title": f"👤 {config.channel_id}", "on": True})
    elif config.channel_id:
        title = config.channel_id
        if bot is not None:
            try:
                title = (await bot.get_chat(config.channel_id)).title or title
            except Exception:
                pass
        opts.append({"type": "botch", "target": config.channel_id, "title": f"📢 {title}", "on": True})
    chats = await session.scalar(
        select(func.count(BotChat.id)).where(BotChat.active.is_(True), BotChat.type.in_(GROUP_TYPES))) or 0
    if chats:
        opts.append({"type": "chats", "target": "", "title": f"💬 Все чаты с ботом ({chats})", "on": False})
    users = await session.scalar(select(func.count(User.id)).where(User.is_blocked.is_(False))) or 0
    if users:
        opts.append({"type": "users", "target": "", "title": f"📨 Рассылка всем клиентам ({users})", "on": False})
    return opts


async def _targets_screen(target, state: FSMContext) -> None:
    data = await state.get_data()
    opts = data.get("opts") or []
    rows = [[btn(("✅ " if o["on"] else "▫️ ") + o["title"][:56], AIn(a="pt", v=str(i)))] for i, o in enumerate(opts)]
    chosen = sum(1 for o in opts if o["on"])
    rows.append([btn(f"📢 Опубликовать ({chosen})", AIn(a="post_ok"))])
    rows.append([btn("◀️ Отмена", Adm.unpack(data["back"]) if data.get("back") else Adm(s="ch"))])
    note = "" if data.get("account_ok", True) else "\n\n⚠️ Такой тип сообщения аккаунт не публикует, он уйдёт только в чаты с ботом."
    text = ("📍 <b>Куда отправить?</b> Пост выше: так его увидят.\n\n"
            "👤 ваши каналы (публикует ваш аккаунт, премиум эмодзи сохраняются)\n"
            "📢 канал от имени бота\n💬 все группы, куда добавлен бот\n📨 личным сообщением всем клиентам бота" + note)
    if not opts:
        text = "Некуда публиковать: укажите CHANNEL_ID в .env или добавьте бота в группу."
    await show(target, text, kb(*rows))


@router.message(AdmSt.post)
async def post_input(message: Message, state: FSMContext, session: AsyncSession) -> None:
    file_id, kind, name = posting.media_of(message)
    text = message.text or message.caption or ""
    ents = entities_to_store(message.entities if message.text else message.caption_entities)
    account_ok = bool(file_id or message.text)
    await state.set_state(AdmSt.post_confirm)
    await state.set_data({
        "from_chat": message.chat.id, "msg_id": message.message_id, "text": text, "entities": ents,
        "file_id": file_id, "kind": kind, "name": name, "account_ok": account_ok,
        "photo": file_id if kind == "photo" else None, "opts": await _options(session, message.bot),
    })
    await message.answer("👀 <b>Так пост будет выглядеть:</b>")
    try:
        await message.copy_to(message.chat.id)
    except TelegramBadRequest:
        pass
    await _targets_screen(message, state)


@router.callback_query(AdmSt.post_confirm, AIn.filter(F.a == "pt"))
async def post_toggle(cb: CallbackQuery, callback_data: AIn, state: FSMContext) -> None:
    data = await state.get_data()
    opts = data.get("opts") or []
    i = int(callback_data.v or -1)
    if 0 <= i < len(opts):
        opts[i]["on"] = not opts[i]["on"]
        await state.update_data(opts=opts)
    await _targets_screen(cb, state)


@router.callback_query(AdmSt.post_confirm, AIn.filter(F.a == "post_ok"))
async def post_ok(cb: CallbackQuery, state: FSMContext, session: AsyncSession, sm) -> None:
    data = await state.get_data()
    chosen = [o for o in (data.get("opts") or []) if o["on"]]
    if not chosen:
        await answer(cb, "Отметьте хотя бы один канал или чат", alert=True)
        return
    await state.clear()
    await show(cb, "⏳ Публикую...")
    report = []
    acc = [o for o in chosen if o["type"] == "acc"]
    if acc and data.get("account_ok"):
        base = ""
        if data.get("file_id"):
            base = await posting.download_media(cb.bot, data["file_id"], data["kind"], data.get("name", ""))
        for o in acc:
            media = posting.clone_media(base) if base else ""
            await posting.queue_account(session, o["target"], data["text"], data["entities"], media, data["kind"] or "")
        await session.commit()
        if base:
            try:
                os.remove(base)
            except OSError:
                pass
        report.append(f"👤 В очереди аккаунта: {len(acc)} (уйдут в течение минуты, с паузами)")
    elif acc:
        report.append("⚠️ Аккаунт такой тип сообщения не публикует, каналы пропущены")
    for o in chosen:
        if o["type"] == "botch":
            ok, info = await posting.copy_by_bot(cb.bot, o["target"], data["from_chat"], data["msg_id"],
                                                 data["text"], data["entities"], data.get("photo"))
            report.append(("✅ " if ok else "⚠️ ") + f"{o['title']}: {info}")
    if any(o["type"] == "chats" for o in chosen):
        asyncio.create_task(posting.run_chats(cb.bot, sm, data["from_chat"], data["msg_id"], cb.from_user.id))
        report.append("💬 Рассылка в чаты запущена, отчёт придёт сообщением")
    if any(o["type"] == "users" for o in chosen):
        from . import broadcast

        if broadcast.start(cb.bot, sm, "all", data["from_chat"], data["msg_id"], cb.from_user.id):
            report.append("📨 Рассылка клиентам запущена, отчёт придёт сообщением")
        else:
            report.append("⚠️ Уже идёт другая рассылка клиентам, дождитесь окончания")
    if data.get("history"):
        hist = list(settings.get("rates_history") or [])
        hist.insert(0, data["history"])
        await settings.put(session, "rates_history", hist[:30])
        await session.commit()
    await show(cb, "📢 <b>Готово</b>\n\n" + h("\n".join(report)), kb(
        [btn("✍️ Ещё пост", Adm(s="ch", a="new")), btn("📄 Очередь", Adm(s="ch", a="queue"))],
        [btn("◀️ Посты", Adm(s="ch"))],
    ))


async def start_text_post(cb: CallbackQuery, state: FSMContext, session: AsyncSession, text: str,
                          ents: list[dict] | None, back: Adm, title: str, history: dict | None = None,
                          photo: str | None = None) -> None:
    """Готовый пост (курсы, подарок, звёзды, Premium): превью и выбор, куда отправить."""
    await show(cb, title)

    async def _send(entities):
        if photo:
            return await cb.bot.send_photo(cb.from_user.id, photo, caption=text[:1024],
                                           caption_entities=entities_from_store(entities), parse_mode=None)
        return await cb.bot.send_message(cb.from_user.id, text, entities=entities_from_store(entities), parse_mode=None)

    try:
        msg = await _send(ents)
    except TelegramBadRequest:
        ents = strip_custom_emoji(ents)
        msg = await _send(ents)
    msg = msg.as_(cb.bot)
    await state.set_state(AdmSt.post_confirm)
    await state.set_data({
        "from_chat": msg.chat.id, "msg_id": msg.message_id, "text": text[:1024] if photo else text, "entities": ents or [],
        "file_id": photo, "kind": "photo" if photo else "", "name": "", "account_ok": True, "photo": photo,
        "opts": await _options(session, cb.bot), "back": back.pack(), "history": history,
    })
    await _targets_screen(msg, state)
