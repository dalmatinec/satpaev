from aiogram import F, Router
from aiogram.filters import CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from ..cb import Adm, Nav
from ..db.models import User
from ..services import settings
from ..ui import answer, btn, kb, send_safe, show

router = Router(name="start")


def main_kb(is_admin: bool):
    site = str(settings.get("site_url") or "")
    site_btn = btn("🌐 Наш сайт", url=site) if site.startswith(("http://", "https://")) else btn("🌐 Наш сайт", Nav(to="site"))
    rows = [
        [btn("⭐ Звёзды", Nav(to="stars")), btn("🎁 NFT подарки", Nav(to="gifts"))],
        [btn("💎 Юзернеймы", Nav(to="un")), btn("💱 Обмен", Nav(to="ex"))],
        [btn("🛠 Разработка и сервера", Nav(to="dev"))],
        [btn("📦 Мои заказы", Nav(to="orders")), btn("👥 Рефералы", Nav(to="ref"))],
        [btn("💬 Связаться", Nav(to="support")), btn("⭐ Отзывы", Nav(to="reviews"))],
        [site_btn],
    ]
    if is_admin:
        rows.append([btn("⚙️ Админка", Adm(s="menu"))])
    return kb(*rows)


@router.message(CommandStart())
async def cmd_start(
    message: Message,
    command: CommandObject,
    session: AsyncSession,
    user: User,
    is_new_user: bool,
    is_admin: bool,
    state: FSMContext,
) -> None:
    await state.clear()
    args = (command.args or "").strip()
    if is_new_user and args.startswith("r") and args[1:].isdigit():
        ref_id = int(args[1:])
        if ref_id != user.id and await session.get(User, ref_id):
            user.referrer_id = ref_id
            await session.commit()
            await send_safe(message.bot, ref_id, "🎉 По вашей ссылке пришёл новый друг! Вы получите процент с его заказов.")
    await show(message, settings.rich("welcome"), main_kb(is_admin))


@router.callback_query(Nav.filter(F.to == "menu"))
async def nav_menu(cb: CallbackQuery, is_admin: bool) -> None:
    await show(cb, settings.rich("welcome"), main_kb(is_admin))


@router.callback_query(Nav.filter(F.to == "site"))
async def nav_site(cb: CallbackQuery) -> None:
    await answer(cb, "🌐 Сайт скоро откроется. Следите за новостями в канале!", alert=True)
