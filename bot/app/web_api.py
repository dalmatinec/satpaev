"""Небольшой API для сайта. Только чтение, без админских действий: всё управление в боте.

Защита:
- слушает внутри Docker, наружу проброшен только на 127.0.0.1, сайт ходит через nginx;
- только GET, строгая проверка параметров, лимит запросов на IP, кэш ответов;
- никаких CORS заголовков: чужие сайты не смогут читать ответы из браузера.
"""

import logging
import time

from aiohttp import web
from aiogram import Bot
from sqlalchemy import select

from .db.models import Rate
from .services import settings, username_check
from .texts import TEXTS, strip_html
from .utils import USERNAME_RE

log = logging.getLogger(__name__)

SITE_TTL = 20
_site_cache: tuple[float, dict] | None = None

# для экрана «🌐 Сайт и Web App» в админке
STATS: dict = {"running": False, "port": 0, "error": "", "last": 0.0, "hours": {}}


def _hit() -> None:
    now = time.time()
    STATS["last"] = now
    hour = int(now // 3600)
    hours = STATS["hours"]
    hours[hour] = hours.get(hour, 0) + 1
    for old in [h for h in hours if h < hour - 24]:
        del hours[old]


def hits(last_hours: int = 24) -> int:
    hour = int(time.time() // 3600)
    return sum(v for h, v in STATS["hours"].items() if h > hour - last_hours)


class Limiter:
    """Простой лимит: не больше N запросов за окно на один IP."""

    def __init__(self, limit: int, window: float) -> None:
        self.limit, self.window = limit, window
        self.hits: dict[str, tuple[float, int]] = {}

    def allow(self, ip: str) -> bool:
        now = time.monotonic()
        start, count = self.hits.get(ip, (now, 0))
        if now - start > self.window:
            start, count = now, 0
        count += 1
        self.hits[ip] = (start, count)
        if len(self.hits) > 50000:
            self.hits.clear()
        return count <= self.limit


site_limit = Limiter(120, 60)
user_limit = Limiter(30, 60)


def _ip(request: web.Request) -> str:
    return request.headers.get("X-Real-IP") or request.remote or "?"


def _json(data: dict, status: int = 200, cache: int = 0) -> web.Response:
    resp = web.json_response(data, status=status)
    resp.headers["Cache-Control"] = f"public, max-age={cache}" if cache else "no-store"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    return resp


async def _build_site(bot: Bot, sm) -> dict:
    from .handlers.stars import min_qty

    async with sm() as session:
        rates = (await session.execute(
            select(Rate).where(Rate.is_active.is_(True)).order_by(Rate.sort, Rate.id)
        )).scalars().all()
    me = await bot.me()
    texts = {k: strip_html(settings.t(k)) for k, spec in TEXTS.items() if spec.group == "site"}
    return {
        "brand": strip_html(str(settings.get("brand") or "")),
        "bot": me.username,
        "min_order": float(settings.min_order()),
        "ton_kzt": float(settings.get("ton_kzt") or 0),
        "sla": {k: str(settings.get(f"sla_{k}") or "") for k in ("stars", "exchange", "gifts")},
        "rates": [
            {"code": r.code, "buy": float(r.buy) if r.buy else None, "sell": float(r.sell) if r.sell else None,
             "min": float(r.min_qty) if r.min_qty else None}
            for r in rates if r.buy or r.sell
        ],
        "stars": {"tiers": [[q, p] for q, p in settings.star_tiers()], "min_qty": min_qty()},
        "texts": texts,
    }


def make_app(bot: Bot, sm) -> web.Application:
    async def site(request: web.Request) -> web.Response:
        global _site_cache
        _hit()
        if not site_limit.allow(_ip(request)):
            return _json({"error": "too_many_requests"}, 429)
        now = time.monotonic()
        if _site_cache is None or now - _site_cache[0] > SITE_TTL:
            try:
                _site_cache = (now, await _build_site(bot, sm))
            except Exception:
                log.exception("api site failed")
                return _json({"error": "unavailable"}, 503)
        return _json(_site_cache[1], cache=SITE_TTL)

    async def username(request: web.Request) -> web.Response:
        _hit()
        if not user_limit.allow(_ip(request)):
            return _json({"error": "too_many_requests"}, 429)
        raw = (request.query.get("u") or "")[:40]
        m = USERNAME_RE.match(raw.strip())
        if not m:
            return _json({"error": "bad_username"}, 400)
        result = await username_check.check_full(m.group(1))
        out = {k: result[k] for k in ("status", "price_ton", "ends_at") if k in result}
        out["username"] = m.group(1).lower()
        out["checked_at"] = int(time.time())
        return _json(out, cache=15)

    async def health(request: web.Request) -> web.Response:
        return _json({"ok": True})

    app = web.Application(client_max_size=1024)
    app.router.add_get("/api/site", site)
    app.router.add_get("/api/username", username)
    app.router.add_get("/api/health", health)
    return app


async def start(bot: Bot, sm, port: int) -> web.AppRunner | None:
    """Запуск API. Если не получилось, бот работает дальше, а причина видна в админке."""
    STATS["port"] = port
    try:
        runner = web.AppRunner(make_app(bot, sm), access_log=None)
        await runner.setup()
        await web.TCPSite(runner, "0.0.0.0", port).start()
    except Exception as e:
        STATS["error"] = str(e)[:200]
        log.exception("API сайта не запустился")
        return None
    STATS["running"] = True
    log.info("API сайта слушает порт %s", port)
    return runner
