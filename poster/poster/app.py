"""Постер канала от вашего аккаунта (Telethon).

Задача одна: брать посты из очереди в базе и публиковать их в ваш канал
с премиум эмодзи. Ничего больше аккаунт не делает: не читает чаты,
не принимает апдейты, соблюдает паузы между постами и лимиты Telegram.
"""

import asyncio
import json
import logging
import os
import signal
import sys
from getpass import getpass

import asyncpg
from telethon import TelegramClient, errors
from telethon.tl import types as t

log = logging.getLogger("poster")

API_ID = int(os.getenv("TG_API_ID", "0") or 0)
API_HASH = os.getenv("TG_API_HASH", "").strip()
CHANNEL = os.getenv("CHANNEL_ID", "").strip()
SESSION = os.getenv("POSTER_SESSION", "/session/poster")
MIN_INTERVAL = int(os.getenv("POSTER_MIN_INTERVAL", "20"))  # секунд между постами
MAX_ATTEMPTS = 3

DSN = "postgresql://{u}:{p}@{h}:{port}/{d}".format(
    u=os.getenv("POSTGRES_USER", "satpaev"),
    p=os.getenv("POSTGRES_PASSWORD", ""),
    h=os.getenv("DB_HOST", "db"),
    port=os.getenv("DB_PORT", "5432"),
    d=os.getenv("POSTGRES_DB", "satpaev"),
)

SIMPLE = {
    "bold": t.MessageEntityBold,
    "italic": t.MessageEntityItalic,
    "underline": t.MessageEntityUnderline,
    "strikethrough": t.MessageEntityStrike,
    "spoiler": t.MessageEntitySpoiler,
    "code": t.MessageEntityCode,
    "url": t.MessageEntityUrl,
    "email": t.MessageEntityEmail,
    "phone_number": t.MessageEntityPhone,
    "hashtag": t.MessageEntityHashtag,
    "cashtag": t.MessageEntityCashtag,
    "mention": t.MessageEntityMention,
    "bot_command": t.MessageEntityBotCommand,
}


def convert_entities(raw) -> list:
    """Bot API entities (смещения UTF-16) в entities MTProto (тоже UTF-16)."""
    if isinstance(raw, str):
        raw = json.loads(raw or "[]")
    out = []
    for e in raw or []:
        kind, off, ln = e.get("type"), int(e.get("offset", 0)), int(e.get("length", 0))
        if ln <= 0:
            continue
        try:
            if kind in SIMPLE:
                out.append(SIMPLE[kind](off, ln))
            elif kind == "pre":
                out.append(t.MessageEntityPre(off, ln, e.get("language") or ""))
            elif kind == "text_link":
                out.append(t.MessageEntityTextUrl(off, ln, e.get("url") or ""))
            elif kind == "custom_emoji":
                out.append(t.MessageEntityCustomEmoji(off, ln, int(e["custom_emoji_id"])))
            elif kind in ("blockquote", "expandable_blockquote"):
                try:
                    out.append(t.MessageEntityBlockquote(off, ln, collapsed=(kind == "expandable_blockquote")))
                except TypeError:
                    out.append(t.MessageEntityBlockquote(off, ln))
        except (KeyError, ValueError, TypeError):
            continue
    return out


def make_client() -> TelegramClient:
    client = TelegramClient(
        SESSION,
        API_ID,
        API_HASH,
        device_model="Store Poster",
        system_version="Linux",
        app_version="1.0",
        lang_code="ru",
        system_lang_code="ru",
        receive_updates=False,
        flood_sleep_threshold=0,
        request_retries=3,
        connection_retries=5,
        retry_delay=5,
        auto_reconnect=True,
    )
    client.parse_mode = None
    return client


class Poster:
    def __init__(self) -> None:
        self.pool: asyncpg.Pool | None = None
        self.client: TelegramClient | None = None
        self.channel = None
        self.stop = asyncio.Event()

    async def status(self, state: str, info: str = "") -> None:
        if not self.pool:
            return
        try:
            await self.pool.execute(
                "INSERT INTO poster_status (id, state, info, updated_at) VALUES (1, $1, $2, now()) "
                "ON CONFLICT (id) DO UPDATE SET state = $1, info = $2, updated_at = now()",
                state, info[:250],
            )
        except Exception as e:
            log.warning("status write failed: %s", e)

    async def connect_db(self) -> None:
        while not self.stop.is_set():
            try:
                self.pool = await asyncpg.create_pool(DSN, min_size=1, max_size=2, command_timeout=30)
                # таблицы создаёт бот, ждём их
                await self.pool.fetchval("SELECT 1 FROM posts LIMIT 1")
                await self.pool.fetchval("SELECT 1 FROM poster_status LIMIT 1")
                return
            except Exception as e:
                log.info("Жду базу и таблицы бота: %s", e.__class__.__name__)
                if self.pool:
                    await self.pool.close()
                    self.pool = None
                await self.sleep(5)

    async def sleep(self, seconds: float) -> None:
        try:
            await asyncio.wait_for(self.stop.wait(), timeout=seconds)
        except asyncio.TimeoutError:
            pass

    async def recover(self) -> None:
        # если процесс упал посреди отправки, НЕ шлём повторно (чтобы не было дублей в канале)
        await self.pool.execute(
            "UPDATE posts SET status = 'unknown', error = 'Отправка прервалась, проверьте канал' "
            "WHERE status = 'sending' AND mode = 'account'"
        )

    async def take(self):
        return await self.pool.fetchrow(
            "UPDATE posts SET status = 'sending', attempts = attempts + 1 WHERE id = ("
            "  SELECT id FROM posts WHERE status = 'pending' AND mode = 'account' ORDER BY id LIMIT 1 FOR UPDATE SKIP LOCKED"
            ") RETURNING id, target, text, entities, media, attempts"
        )

    async def resolve(self, target: str):
        target = target or CHANNEL
        if target.lstrip("-").isdigit():
            peer_id = int(target)
            try:
                return await self.client.get_input_entity(peer_id)
            except ValueError:
                # канала нет в кэше сессии: один раз пролистываем диалоги
                async for d in self.client.iter_dialogs(limit=300):
                    if d.id == peer_id:
                        return d.input_entity
                raise
        return await self.client.get_input_entity(target)

    async def send(self, row) -> None:
        entity = await self.resolve(row["target"])
        ents = convert_entities(row["entities"])
        if row["media"] and os.path.exists(row["media"]):
            msg = await self.client.send_file(entity, row["media"], caption=row["text"] or None,
                                              formatting_entities=ents or None)
        else:
            msg = await self.client.send_message(entity, row["text"], formatting_entities=ents or None,
                                                 link_preview=False)
        await self.pool.execute(
            "UPDATE posts SET status = 'sent', remote_id = $2, sent_at = now(), error = '' WHERE id = $1",
            row["id"], msg.id,
        )
        log.info("Пост #%s опубликован", row["id"])

    async def fail(self, row, error: str, retry: bool) -> None:
        status = "pending" if retry and row["attempts"] < MAX_ATTEMPTS else "failed"
        await self.pool.execute("UPDATE posts SET status = $2, error = $3 WHERE id = $1", row["id"], status, error[:500])

    async def work(self) -> None:
        me = await self.client.get_me()
        name = f"{me.first_name or ''} @{me.username or me.id}".strip()
        await self.status("online", name)
        log.info("Аккаунт %s на связи", name)
        await self.recover()
        last_beat = 0.0
        loop = asyncio.get_running_loop()
        while not self.stop.is_set():
            if loop.time() - last_beat > 30:
                await self.status("online", name)
                last_beat = loop.time()
            row = await self.take()
            if not row:
                await self.sleep(5)
                continue
            try:
                await self.send(row)
            except errors.FloodWaitError as e:
                await self.pool.execute("UPDATE posts SET status = 'pending' WHERE id = $1", row["id"])
                await self.status("flood", f"Пауза {e.seconds} сек")
                log.warning("FloodWait %s сек", e.seconds)
                await self.sleep(e.seconds + 5)
                await self.status("online", name)
                continue
            except (errors.ChatWriteForbiddenError, errors.ChatAdminRequiredError, errors.ChannelPrivateError) as e:
                await self.fail(row, f"Нет прав на публикацию в канал: {e.__class__.__name__}", retry=False)
            except ValueError as e:
                await self.fail(row, f"Канал не найден: {e}", retry=False)
            except (errors.AuthKeyError, errors.UnauthorizedError):
                await self.pool.execute("UPDATE posts SET status = 'pending' WHERE id = $1", row["id"])
                raise
            except errors.RPCError as e:
                await self.fail(row, f"Telegram: {e.__class__.__name__}", retry=True)
            except (ConnectionError, OSError, asyncio.TimeoutError) as e:
                # сеть: неизвестно, дошёл ли пост, поэтому без автоповтора
                await self.pool.execute(
                    "UPDATE posts SET status = 'unknown', error = $2 WHERE id = $1", row["id"], f"Сеть: {e}"[:500]
                )
                raise
            await self.sleep(MIN_INTERVAL)

    async def run(self) -> None:
        await self.connect_db()
        if not API_ID or not API_HASH:
            log.warning("TG_API_ID / TG_API_HASH не заданы, постер в режиме ожидания")
            while not self.stop.is_set():
                await self.status("disabled")
                await self.sleep(120)
            return
        backoff = 5
        while not self.stop.is_set():
            self.client = make_client()
            try:
                await self.status("starting")
                await self.client.connect()
                if not await self.client.is_user_authorized():
                    log.warning("Аккаунт не авторизован. Выполните: docker compose run --rm poster python -m poster login")
                    await self.status("unauthorized")
                    await self.client.disconnect()
                    await self.sleep(60)
                    continue
                backoff = 5
                await self.work()
            except (errors.AuthKeyError, errors.UnauthorizedError) as e:
                log.error("Сессия недействительна: %s", e)
                await self.status("unauthorized", "Сессия сброшена, нужен повторный вход")
                await self.sleep(300)
            except asyncio.CancelledError:
                break
            except Exception as e:
                log.exception("Ошибка постера")
                await self.status("error", e.__class__.__name__)
                await self.sleep(backoff)
                backoff = min(backoff * 2, 300)
            finally:
                try:
                    await self.client.disconnect()
                except Exception:
                    pass
        await self.status("starting", "остановлен")


async def main() -> None:
    poster = Poster()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, poster.stop.set)
        except NotImplementedError:
            pass
    await poster.run()
    if poster.pool:
        await poster.pool.close()


async def login() -> None:
    if not API_ID or not API_HASH:
        print("Сначала укажите TG_API_ID и TG_API_HASH в .env (получить на https://my.telegram.org)")
        sys.exit(1)
    client = make_client()
    print("Вход в аккаунт для публикации в канал. Код придёт в Telegram.")
    await client.start(
        phone=lambda: input("Номер телефона (+7...): ").strip(),
        code_callback=lambda: input("Код из Telegram: ").strip(),
        password=lambda: getpass("Облачный пароль (2FA), если есть: "),
    )
    me = await client.get_me()
    print(f"✅ Вошли как {me.first_name} (@{me.username})")
    if CHANNEL:
        try:
            target = int(CHANNEL) if CHANNEL.lstrip("-").isdigit() else CHANNEL
            if isinstance(target, int):
                async for _ in client.iter_dialogs(limit=300):
                    pass
            entity = await client.get_entity(target)
            print(f"✅ Канал найден: {getattr(entity, 'title', CHANNEL)}")
        except Exception as e:
            print(f"⚠️ Канал {CHANNEL} не найден ({e}). Проверьте CHANNEL_ID и что аккаунт админ канала.")
    await client.disconnect()
    for suffix in (".session", ".session-journal"):
        path = SESSION + suffix
        if os.path.exists(path):
            os.chmod(path, 0o600)
    print("Готово. Перезапустите постер: docker compose restart poster")
