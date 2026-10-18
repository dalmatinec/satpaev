"""Telegram Web App: кнопка слева от поля ввода и кнопка сайта в меню открывают сайт внутри Telegram."""

import logging

from aiogram import Bot
from aiogram.types import MenuButtonCommands, MenuButtonWebApp, WebAppInfo

from . import settings

log = logging.getLogger(__name__)


def url() -> str:
    """Ссылка для Web App или пустая строка (Telegram принимает только https)."""
    site = str(settings.get("site_url") or "").strip()
    if settings.get("webapp_enabled") and site.startswith("https://"):
        return site
    return ""


async def apply(bot: Bot, reset: bool = False) -> str:
    """Ставит кнопку Web App у поля ввода. Возвращает пустую строку или текст ошибки.

    Если ссылки нет, кнопку не трогаем: её могли поставить в @BotFather.
    reset=True (админ выключил Web App или убрал ссылку) возвращает обычное меню команд.
    """
    link = url()
    try:
        if link:
            text = (str(settings.get("webapp_menu_text") or "").strip() or "Открыть")[:32]
            await bot.set_chat_menu_button(menu_button=MenuButtonWebApp(text=text, web_app=WebAppInfo(url=link)))
        elif reset:
            await bot.set_chat_menu_button(menu_button=MenuButtonCommands())
        return ""
    except Exception as e:  # сеть или Telegram отклонил ссылку
        log.warning("Не удалось поставить кнопку Web App: %s", e)
        return str(e)
