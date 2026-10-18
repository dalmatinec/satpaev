from aiogram import F, Router
from aiogram.filters import CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from ..cb import Nav
from ..db.models import User
from ..services import media, settings
from ..texts import MENU_KEYS, strip_html
from ..ui import answer, mbtn, screen_kb, send_safe, show
from ..utils import clean_username, h

router = Router(name="start")


def main_kb(is_admin: bool = False):
    site = str(settings.get("site_url") or "")
    buttons = {}
    for key in MENU_KEYS:
        if key == "site" and site.startswith(("http://", "https://")):
            buttons[key] = mbtn("site", url=site)
        else:
            buttons[key] = mbtn(key, Nav(to=key))
    return screen_kb("menu", buttons)


async def show_menu(target, user: User | None, is_admin: bool) -> None:
    name = h(user.full_name.split()[0]) if user and user.full_name else ""
    await show(target, settings.t("welcome", name=name), main_kb(is_admin), photo=media.photo("welcome"),
               edit=("welcome", "menu"))


async def deep_link(payload: str, message: Message, state: FSMContext, session: AsyncSession, user: User) -> bool:
    """Ссылки вида t.me/bot?start=stars_500 с сайта и из постов. True, если обработано."""
    from . import dev, exchange, gifts, my_orders, referral, stars, support, usernames

    if payload.startswith("stars_") and payload[6:].isdigit():
        qty = int(payload[6:])
        if qty >= stars.min_qty():
            await stars.ask_recipient(message, state, user, qty)
            return True
    if payload.startswith("ex_"):
        from sqlalchemy import func, select

        from ..db.models import Rate

        code = payload[3:].upper()[:16]
        r = await session.scalar(select(Rate).where(func.upper(Rate.code) == code, Rate.is_active.is_(True)))
        if r:
            await exchange.pair_view(message, r)
            return True
    if payload.startswith("un_"):
        uname = clean_username(payload[3:])
        if uname:
            await usernames.check_and_confirm(message, state, uname)
            return True
    screens = {
        "stars": lambda: stars.stars_view(message),
        "gifts": lambda: gifts.gift_page(message, session, 0),
        "un": lambda: usernames.un_view(message),
        "ex": lambda: exchange.ex_view(message, session),
        "dev": lambda: dev.dev_view(message, session),
        "ref": lambda: referral.ref_view(message, session, user),
        "support": lambda: support.support_view(message, state),
        "orders": lambda: my_orders.orders_view(message, session, user, 0),
    }
    if payload in screens:
        await screens[payload]()
        return True
    return False


async def apply_referral(session: AsyncSession, bot, user: User, args: str) -> None:
    if args.startswith("r") and args[1:].isdigit():
        ref_id = int(args[1:])
        if ref_id != user.id and not user.referrer_id and await session.get(User, ref_id):
            user.referrer_id = ref_id
            await session.commit()
            await send_safe(bot, ref_id, settings.t("ref_new"))


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
    from ..services import subscription
    from .subscribe import sub_view

    await state.clear()
    args = (command.args or "").strip()
    if is_new_user:
        await apply_referral(session, message.bot, user, args)
    if args and await deep_link(args, message, state, session, user):
        return
    if (not is_admin and subscription.mode() == "recommend" and subscription.should_recommend(user.id)
            and not await subscription.is_subscribed(message.bot, user.id)):
        await sub_view(message, required=False)
        return
    await show_menu(message, user, is_admin)


@router.callback_query(Nav.filter(F.to == "menu"))
async def nav_menu(cb: CallbackQuery, user: User, is_admin: bool) -> None:
    await show_menu(cb, user, is_admin)


@router.callback_query(Nav.filter(F.to == "site"))
async def nav_site(cb: CallbackQuery) -> None:
    await answer(cb, strip_html(settings.t("site_soon")), alert=True)
