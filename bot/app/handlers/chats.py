"""Учёт групп и каналов, куда добавлен бот (для рассылки постов в чаты)."""

from aiogram import Router
from aiogram.types import ChatMemberUpdated
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import BotChat
from ..utils import utcnow

router = Router(name="chats")

ACTIVE = {"member", "administrator", "creator"}


@router.my_chat_member()
async def on_my_chat_member(event: ChatMemberUpdated, session: AsyncSession) -> None:
    chat = event.chat
    if chat.type == "private":
        return
    row = await session.get(BotChat, chat.id)
    if row is None:
        row = BotChat(id=chat.id)
        session.add(row)
    row.type = chat.type
    row.title = (chat.title or "")[:256]
    row.username = (chat.username or "")[:64]
    row.active = event.new_chat_member.status in ACTIVE
    row.updated_at = utcnow()
    await session.commit()
