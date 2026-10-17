"""Предварительная проверка юзернейма по открытой странице Fragment. Без ключей и API."""

import asyncio
import logging
import re

import aiohttp

log = logging.getLogger(__name__)

_STATUS_RE = re.compile(r'tm-section-header-status[^"]*"[^>]*>\s*([^<]+?)\s*<', re.IGNORECASE)

STATUS_RU = {
    "available": "🟢 Выставлен на продажу на Fragment",
    "on auction": "🔨 Сейчас на аукционе Fragment",
    "for sale": "🟢 Продаётся на Fragment",
    "sold": "🔴 Продан на Fragment, есть владелец",
    "taken": "🟠 Занят пользователем",
    "not for sale": "🟠 Занят, не продаётся",
    "unavailable": "⚪ Свободен или недоступен для аукциона",
}

_session: aiohttp.ClientSession | None = None


def _get_session() -> aiohttp.ClientSession:
    global _session
    if _session is None or _session.closed:
        _session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=6),
            headers={"User-Agent": "Mozilla/5.0 (compatible; StoreBot/1.0)"},
        )
    return _session


async def check(username: str) -> str:
    try:
        async with _get_session().get(f"https://fragment.com/username/{username}", allow_redirects=True) as resp:
            if resp.status != 200:
                return "❔ Не удалось проверить автоматически, менеджер проверит вручную"
            html = await resp.text(errors="ignore")
            if "/username/" not in str(resp.url):
                # Fragment перенаправил на поиск: такого юзера там нет
                return "⚪ На Fragment не найден, менеджер проверит вручную"
    except (aiohttp.ClientError, asyncio.TimeoutError) as e:
        log.info("fragment check failed: %s", e)
        return "❔ Не удалось проверить автоматически, менеджер проверит вручную"
    m = _STATUS_RE.search(html)
    if not m:
        return "❔ Статус не определён, менеджер проверит вручную"
    raw = m.group(1).strip().lower()
    return STATUS_RU.get(raw, f"ℹ️ Fragment: {m.group(1).strip()}")


async def close() -> None:
    if _session and not _session.closed:
        await _session.close()
