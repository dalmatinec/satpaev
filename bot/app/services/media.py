"""Картинки разделов (приветствие и др.).

Показываются по file_id (быстро, без загрузки), а сам файл лежит в базе на сервере
и попадает в ежедневный бэкап. Если file_id перестал работать (например, после
восстановления на новом боте), картинка перезаливается из базы автоматически.
"""

import io
import logging

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import BufferedInputFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import config
from ..db.models import Media

log = logging.getLogger(__name__)

MAX_BYTES = 5 * 1024 * 1024
_ids: dict[str, str] = {}


async def load(session_maker) -> None:
    async with session_maker() as session:
        rows = (await session.execute(select(Media.key, Media.file_id))).all()
    _ids.clear()
    _ids.update({k: f for k, f in rows if f})


def photo(key: str) -> str | None:
    return _ids.get(key)


async def save(session: AsyncSession, bot: Bot, key: str, file_id: str) -> None:
    buf = io.BytesIO()
    await bot.download(file_id, destination=buf)
    data = buf.getvalue()
    row = await session.get(Media, key)
    if row is None:
        row = Media(key=key)
        session.add(row)
    row.file_id = file_id
    row.data = data if len(data) <= MAX_BYTES else None
    await session.commit()
    _ids[key] = file_id


async def remove(session: AsyncSession, key: str) -> None:
    row = await session.get(Media, key)
    if row is not None:
        await session.delete(row)
        await session.commit()
    _ids.pop(key, None)


async def verify(bot: Bot, session_maker) -> None:
    """Проверяет file_id при старте и перезаливает картинки, если бот сменился."""
    if not config.owner_id:
        return
    async with session_maker() as session:
        rows = (await session.execute(select(Media))).scalars().all()
        for row in rows:
            try:
                await bot.get_file(row.file_id)
                continue
            except TelegramBadRequest:
                pass
            if not row.data:
                continue
            try:
                msg = await bot.send_photo(
                    config.owner_id, BufferedInputFile(row.data, filename=f"{row.key}.jpg"),
                    disable_notification=True,
                )
                row.file_id = msg.photo[-1].file_id
                _ids[row.key] = row.file_id
                await bot.delete_message(config.owner_id, msg.message_id)
                log.info("Картинка %s перезалита", row.key)
            except (TelegramBadRequest, TelegramForbiddenError) as e:
                log.warning("Не удалось перезалить картинку %s: %s", row.key, e)
        await session.commit()
