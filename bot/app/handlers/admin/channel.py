from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...cb import Adm, AIn
from ...config import config
from ...db.models import Post
from ...services import posting, settings
from ...states import AdmSt
from ...ui import answer, btn, kb, show
from ...utils import entities_to_store, fdate, h
from .common import screen

router = Router(name="admin_channel")

POST_ICONS = {"pending": "⏳", "sending": "📤", "sent": "✅", "failed": "⚠️", "unknown": "❔"}


@screen("ch")
async def view(target, session: AsyncSession, cbd: Adm) -> None:
    if cbd.a == "queue":
        await queue(target, session)
        return
    online, state_txt, info = await poster_status(session)
    counts = dict((await session.execute(
        select(Post.status, func.count(Post.id)).group_by(Post.status)
    )).all())
    mode = settings.get("post_mode")
    mode_txt = "👤 через ваш аккаунт (премиум эмодзи)" if mode == "account" else "🤖 через бота"
    text = (
        "📢 <b>Канал</b>\n\n"
        f"Канал: <code>{h(config.channel_id or 'не задан в .env')}</code>\n"
        f"Публикация: <b>{mode_txt}</b>\n"
        f"Постер аккаунта: {state_txt}" + (f" · {h(info)}" if info else "") + "\n\n"
        f"Очередь: ⏳ {counts.get('pending', 0)} · ✅ {counts.get('sent', 0)} · ⚠️ {counts.get('failed', 0) + counts.get('unknown', 0)}"
    )
    if not config.poster_enabled:
        text += "\n\n<i>Чтобы постить с премиум эмодзи от вашего аккаунта, укажите TG_API_ID и TG_API_HASH в .env и войдите командой из README.</i>"
    await show(target, text, kb(
        [btn("✍️ Новый пост", Adm(s="ch", a="new"))],
        [btn("💱 Курсы в канал", Adm(s="rates", a="post")), btn("📄 Очередь", Adm(s="ch", a="queue"))],
        [btn("🔁 Сменить способ публикации", Adm(s="ch", a="mode"))],
        [btn("⚙️ Админка", Adm(s="menu"))],
    ))


async def poster_status(session):
    return await posting.poster_status(session)


async def queue(target, session: AsyncSession) -> None:
    posts = (await session.execute(select(Post).order_by(Post.id.desc()).limit(10))).scalars().all()
    lines = []
    b = InlineKeyboardBuilder()
    for p in posts:
        preview = (p.text or "фото").replace("\n", " ")[:40]
        lines.append(f"{POST_ICONS.get(p.status, '•')} #{p.id} · {fdate(p.created_at)} · {h(preview)}"
                     + (f"\n   <i>{h(p.error[:120])}</i>" if p.error and p.status != "sent" else ""))
        if p.status in ("failed", "unknown"):
            b.button(text=f"🔁 Повторить #{p.id}", callback_data=Adm(s="ch", a="retry", i=p.id))
    b.adjust(2)
    b.row(btn("◀️ Канал", Adm(s="ch")))
    await show(target, "📄 <b>Последние посты</b>\n\n" + ("\n".join(lines) or "Постов ещё не было.") +
               "\n\n❔ значит отправка прервалась: проверьте канал, прежде чем повторять.", b.as_markup())


@router.callback_query(Adm.filter(F.s == "ch"))
async def on_channel(cb: CallbackQuery, callback_data: Adm, session: AsyncSession, state: FSMContext) -> None:
    a = callback_data.a
    if a == "new":
        await state.set_state(AdmSt.post)
        await show(cb, "✍️ Пришлите пост одним сообщением: текст или фото с подписью.\n\n"
                       "Премиум эмодзи и форматирование сохранятся.", kb([btn("◀️ Отмена", Adm(s="ch"))]))
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


@router.message(AdmSt.post)
async def post_input(message: Message, state: FSMContext) -> None:
    if message.photo:
        data = {"text": message.caption or "", "entities": entities_to_store(message.caption_entities),
                "photo": message.photo[-1].file_id}
    elif message.text:
        data = {"text": message.text, "entities": entities_to_store(message.entities), "photo": None}
    else:
        await message.answer("Поддерживается текст или одно фото с подписью.")
        return
    await state.set_state(AdmSt.post_confirm)
    await state.update_data(**data)
    await message.answer("👀 <b>Так пост будет выглядеть:</b>")
    try:
        await message.copy_to(message.chat.id)
    except TelegramBadRequest:
        pass
    await message.answer("Публикуем?", reply_markup=kb(
        [btn("📢 Опубликовать", AIn(a="post_ok"))],
        [btn("◀️ Отмена", Adm(s="ch"))],
    ))


@router.callback_query(AdmSt.post_confirm, AIn.filter(F.a == "post_ok"))
async def post_ok(cb: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    data = await state.get_data()
    await state.clear()
    ok, info = await posting.publish(session, cb.bot, data.get("text", ""), data.get("entities"),
                                     photo_file_id=data.get("photo"), kind="news")
    await show(cb, ("✅ " if ok else "⚠️ ") + h(info), kb([btn("✍️ Ещё пост", Adm(s="ch", a="new"))],
                                                         [btn("◀️ Канал", Adm(s="ch"))]))
