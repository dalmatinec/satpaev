"""Бэкап базы: pg_dump раз в сутки, файл на сервере + в личку владельцу. Старые удаляются."""

import asyncio
import glob
import logging
import os
from datetime import datetime

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import FSInputFile

from ..config import config
from . import settings

log = logging.getLogger(__name__)

TG_LIMIT = 49 * 1024 * 1024
_lock = asyncio.Lock()


def _size(n: int) -> str:
    for unit in ("Б", "КБ", "МБ", "ГБ"):
        if n < 1024:
            return f"{n:.0f} {unit}"
        n /= 1024
    return f"{n:.1f} ТБ"


async def _dump(path: str) -> None:
    url = config.db_url
    env = {**os.environ, "PGPASSWORD": url.password or ""}
    proc = await asyncio.create_subprocess_exec(
        "pg_dump", "-h", url.host or "db", "-p", str(url.port or 5432), "-U", url.username or "",
        "-d", url.database or "", "-Fc", "-Z", "6", "-f", path,
        env=env, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
    )
    try:
        _, err = await asyncio.wait_for(proc.communicate(), timeout=900)
    except asyncio.TimeoutError:
        proc.kill()
        raise RuntimeError("pg_dump не уложился в 15 минут")
    if proc.returncode != 0:
        raise RuntimeError((err or b"").decode(errors="ignore")[-500:] or "pg_dump завершился с ошибкой")


async def make_backup(bot: Bot, session_maker) -> tuple[bool, str]:
    if not config.is_postgres:
        return False, "Бэкап работает только с PostgreSQL"
    async with _lock:
        os.makedirs(config.backup_dir, exist_ok=True)
        stamp = datetime.now(config.tz).strftime("%Y%m%d_%H%M%S")
        path = os.path.join(config.backup_dir, f"backup_{stamp}.dump")
        tmp = path + ".part"
        try:
            await _dump(tmp)
            os.replace(tmp, path)
        except Exception as e:
            with_suppress_remove(tmp)
            log.exception("backup failed")
            await _tell(bot, f"⚠️ Бэкап не создан: {e}")
            return False, str(e)

        # оставляем только последние BACKUP_KEEP файлов
        files = sorted(glob.glob(os.path.join(config.backup_dir, "backup_*.dump")))
        for old in files[: -config.backup_keep]:
            with_suppress_remove(old)

        size = os.path.getsize(path)
        info = {"file": os.path.basename(path), "size": size, "at": stamp}
        sent_id = None
        if config.owner_id:
            prev = (settings.get("backup_last") or {}).get("msg_id")
            if size <= TG_LIMIT:
                try:
                    msg = await bot.send_document(
                        config.owner_id,
                        FSInputFile(path),
                        caption=f"💾 <b>Бэкап базы</b>\n{datetime.now(config.tz).strftime('%d.%m.%Y %H:%M')} · {_size(size)}\n\n"
                                f"Восстановление: положить файл в папку backups и выполнить <code>./restore.sh</code>",
                        disable_notification=True,
                    )
                    sent_id = msg.message_id
                except (TelegramBadRequest, TelegramForbiddenError) as e:
                    log.warning("backup send failed: %s", e)
            else:
                await _tell(bot, f"💾 Бэкап создан ({_size(size)}), он больше лимита Telegram, лежит на сервере: backups/{info['file']}")
            if prev and sent_id:
                try:
                    await bot.delete_message(config.owner_id, prev)
                except TelegramBadRequest:
                    pass
            info["msg_id"] = sent_id or prev
        async with session_maker() as session:
            await settings.put(session, "backup_last", info)
            await session.commit()
        return True, f"{info['file']} · {_size(size)}"


def with_suppress_remove(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass


async def _tell(bot: Bot, text: str) -> None:
    if config.owner_id:
        try:
            await bot.send_message(config.owner_id, text)
        except (TelegramBadRequest, TelegramForbiddenError):
            pass


def size_text(n: int | None) -> str:
    return _size(n or 0)
