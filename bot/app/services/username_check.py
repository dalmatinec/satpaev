"""Проверка юзернейма по открытой странице Fragment. Без ключей и API.

Результат кэшируется на 25 секунд, к Fragment ходим не чаще 3 раз в секунду всего,
поэтому даже наплыв посетителей сайта не создаст нагрузку и не вызовет бан.
"""

import asyncio
import logging
import re
import time

import aiohttp

log = logging.getLogger(__name__)

_STATUS_RE = re.compile(r'tm-section-header-status[^"]*"[^>]*>\s*([^<]+?)\s*<', re.IGNORECASE)
_PRICE_RE = re.compile(r'icon-ton[^"]*"[^>]*>\s*([\d][\d,\s\.]*)\s*<', re.IGNORECASE)
_TIME_RE = re.compile(r'<time[^>]+datetime="([^"]+)"', re.IGNORECASE)

# статус Fragment: (ключ, текст для бота)
STATUS = {
    "available": ("sale", "🟢 Продаётся на Fragment"),
    "for sale": ("sale", "🟢 Продаётся на Fragment"),
    "on auction": ("auction", "🔨 Сейчас на аукционе Fragment"),
    "sold": ("sold", "🔴 Продан на Fragment, есть владелец"),
    "taken": ("taken", "🟠 Занят пользователем"),
    "not for sale": ("taken", "🟠 Занят, не продаётся"),
    "unavailable": ("free", "⚪ Свободен или недоступен для аукциона"),
}
UNKNOWN = {"status": "unknown", "label": "❔ Не удалось проверить автоматически, менеджер проверит вручную"}

CACHE_TTL = 25
_cache: dict[str, tuple[float, dict]] = {}
_sem = asyncio.Semaphore(3)
_session: aiohttp.ClientSession | None = None


def _get_session() -> aiohttp.ClientSession:
    global _session
    if _session is None or _session.closed:
        _session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=6),
            headers={"User-Agent": "Mozilla/5.0 (compatible; StoreBot/1.0)"},
        )
    return _session


def _num(raw: str) -> float | None:
    try:
        return float(raw.replace(",", "").replace(" ", ""))
    except ValueError:
        return None


async def check_full(username: str) -> dict:
    """{'status': sale|auction|sold|taken|free|notfound|unknown, 'label', 'price_ton'?, 'ends_at'?}"""
    name = username.lower()
    now = time.monotonic()
    hit = _cache.get(name)
    if hit and now - hit[0] < CACHE_TTL:
        return hit[1]
    async with _sem:
        try:
            async with _get_session().get(f"https://fragment.com/username/{name}", allow_redirects=True) as resp:
                if resp.status != 200:
                    return dict(UNKNOWN)
                html = await resp.text(errors="ignore")
                if "/username/" not in str(resp.url):
                    result = {"status": "notfound", "label": "⚪ На Fragment не найден, менеджер проверит вручную"}
                    _store(name, result)
                    return result
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            log.info("fragment check failed: %s", e)
            return dict(UNKNOWN)
        finally:
            await asyncio.sleep(0.3)
    m = _STATUS_RE.search(html)
    if not m:
        return dict(UNKNOWN)
    raw = m.group(1).strip()
    key, label = STATUS.get(raw.lower(), ("other", f"ℹ️ Fragment: {raw}"))
    result = {"status": key, "label": label, "fragment": raw}
    price = _PRICE_RE.search(html)
    if price and key in ("sale", "auction", "sold"):
        result["price_ton"] = _num(price.group(1))
    ends = _TIME_RE.search(html)
    if ends and key == "auction":
        result["ends_at"] = ends.group(1)
    _store(name, result)
    return result


def _store(name: str, result: dict) -> None:
    if len(_cache) > 5000:
        _cache.clear()
    _cache[name] = (time.monotonic(), result)


async def check(username: str) -> str:
    """Короткий текст статуса для бота."""
    return (await check_full(username))["label"]


async def close() -> None:
    if _session and not _session.closed:
        await _session.close()
