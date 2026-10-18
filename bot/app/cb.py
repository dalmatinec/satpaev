"""Callback data. Префикс in: и ai: означает «кнопка внутри ввода» (состояние FSM не сбрасывается)."""

from aiogram.filters.callback_data import CallbackData


class Nav(CallbackData, prefix="n"):
    to: str
    p: int = 0


class Shop(CallbackData, prefix="s"):
    """Клиентские разделы: sec = stars, gift, un, ex, dev, ord, rev."""

    sec: str
    a: str = ""
    i: int = 0
    p: int = 0
    v: str = ""


class In(CallbackData, prefix="in"):
    """Кнопки внутри клиентского ввода."""

    a: str
    v: str = ""


class Adm(CallbackData, prefix="a"):
    s: str
    a: str = ""
    i: int = 0
    p: int = 0
    v: str = ""


class AIn(CallbackData, prefix="ai"):
    """Кнопки внутри ввода в админке."""

    a: str
    v: str = ""


class Sub(CallbackData, prefix="sb"):
    """Кнопки экрана подписки (не блокируются проверкой подписки)."""

    a: str
