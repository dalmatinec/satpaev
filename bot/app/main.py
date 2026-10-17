import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ChatType, ParseMode
from aiogram.fsm.storage.base import BaseStorage
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, ErrorEvent

from .config import config
from .db import init_db
from .handlers import build_routers
from .middlewares import AppMiddleware, ResetStateMiddleware
from .services import scheduler, settings, username_check

log = logging.getLogger("bot")


def _storage() -> BaseStorage:
    if config.redis_url:
        from aiogram.fsm.storage.redis import RedisStorage

        # ввод, брошенный на полпути, сам удаляется через сутки
        return RedisStorage.from_url(config.redis_url, state_ttl=86400, data_ttl=86400)
    return MemoryStorage()


async def on_error(event: ErrorEvent) -> bool:
    log.exception("Ошибка при обработке апдейта", exc_info=event.exception)
    return True


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stdout,
    )
    logging.getLogger("aiogram.event").setLevel(logging.WARNING)
    if not config.bot_token:
        log.error("BOT_TOKEN не задан в .env")
        sys.exit(1)
    if not config.admin_ids:
        log.warning("ADMIN_IDS не задан: админка недоступна")

    engine, sm = await init_db()
    await settings.load(sm)

    bot = Bot(config.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML, link_preview_is_disabled=True))
    dp = Dispatcher(storage=_storage())
    dp.update.outer_middleware(AppMiddleware(sm))
    dp.callback_query.outer_middleware(ResetStateMiddleware())
    dp.message.filter(F.chat.type == ChatType.PRIVATE)
    dp.include_routers(*build_routers())
    dp.errors.register(on_error)

    await bot.set_my_commands([BotCommand(command="start", description="Главное меню")])
    tick = asyncio.create_task(scheduler.run(bot, sm))
    me = await bot.me()
    log.info("Бот @%s запущен", me.username)
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types(), sm=sm, handle_signals=True)
    finally:
        tick.cancel()
        await username_check.close()
        try:
            await dp.fsm.storage.close()
        except Exception:
            pass
        await bot.session.close()
        await engine.dispose()


def run() -> None:
    try:
        import uvloop

        uvloop.install()
    except ImportError:
        pass
    asyncio.run(main())
