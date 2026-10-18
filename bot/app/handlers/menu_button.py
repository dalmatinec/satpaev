"""Кнопка «🏠 Главное меню» под полем ввода: всегда видна, возвращает в меню из любого места.

Слева от поля ввода стоит кнопка Web App, поэтому привычного меню команд нет. Эта кнопка заменяет /start.
Роутер подключается первым: кнопка срабатывает даже посреди ввода суммы или заявки.
"""

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, Filter
from aiogram.fsm.context import FSMContext
from aiogram.types import KeyboardButton, Message, ReplyKeyboardMarkup, ReplyKeyboardRemove
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import User
from ..services import settings
from ..ui import _text_kwargs

router = Router(name="menu_button")


def label() -> str:
    return (settings.button("menu_kb")["text"] or "🏠 Главное меню")[:64]


def wanted() -> str:
    """Какая кнопка должна стоять у клиентов сейчас (пусто = никакой)."""
    return label() if settings.get("menu_kb_enabled") else ""


def _markup(icon: bool = True) -> ReplyKeyboardMarkup:
    spec = settings.button("menu_kb")
    extra = {}
    if icon and spec["icon"]:
        extra["icon_custom_emoji_id"] = spec["icon"]
    if icon and spec["style"]:
        extra["style"] = spec["style"]
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text=label(), **extra)]],
                               resize_keyboard=True, is_persistent=True)


async def ensure(message: Message, session: AsyncSession, user: User | None) -> None:
    """Ставит или убирает кнопку у клиента, если она отличается от нужной. Одно короткое сообщение, один раз."""
    if user is None:
        return
    want = wanted()
    if (user.menu_kb or "") == want:
        return
    try:
        if want:
            try:
                await message.answer(**_text_kwargs(settings.t("menu_kb_hint")), reply_markup=_markup())
            except TelegramBadRequest:
                await message.answer(**_text_kwargs(settings.t("menu_kb_hint")), reply_markup=_markup(icon=False))
        else:
            await message.answer("⌨️", reply_markup=ReplyKeyboardRemove())
    except TelegramBadRequest:
        return
    user.menu_kb = want
    await session.commit()


class IsMenuButton(Filter):
    async def __call__(self, message: Message, user: User | None = None) -> bool:
        text = (message.text or "").strip()
        if not text:
            return False
        return text == label() or bool(user and user.menu_kb and text == user.menu_kb)


@router.message(Command("menu"))
@router.message(F.text, IsMenuButton())
async def on_menu_button(message: Message, state: FSMContext, session: AsyncSession, user: User, is_admin: bool) -> None:
    from .start import show_menu

    await state.clear()
    await ensure(message, session, user)
    await show_menu(message, user, is_admin)
