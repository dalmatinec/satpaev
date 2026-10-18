from aiogram import Bot
from aiogram.utils.formatting import Bold, Italic, Text, TextLink

from ..cb import Shop
from ..config import config
from ..db.models import Order, Review, User
from ..ui import btn, kb, send_safe
from . import settings
from .orders import kind_plain


async def ask_review(bot: Bot, order: Order) -> None:
    stars = [btn("⭐" * n, Shop(sec="rev", a="rate", i=order.id, v=str(n))) for n in range(1, 6)]
    await send_safe(
        bot,
        order.user_id,
        settings.t("review_ask", id=order.id),
        kb(stars[4:5], stars[3:4], stars[:3]),
    )


def mask_name(user: User | None) -> str:
    name = (user.full_name if user else "") or "Клиент"
    name = name.split()[0]
    if len(name) <= 2:
        return name[0] + "*"
    return name[:2] + "*" * min(3, len(name) - 2)


def first_name(user: User | None) -> str:
    name = ((user.full_name if user else "") or "Клиент").split()[0]
    return name[:32]


def user_link(user: User | None) -> str:
    if user and user.username:
        return f"https://t.me/{user.username}"
    if user:
        return f"tg://user?id={user.id}"
    return ""


def name_html(user: User | None) -> str:
    """Имя для списка отзывов: ссылкой на профиль или скрытое, по настройке."""
    from html import escape

    if settings.get("reviews_names") == "link" and user:
        return f'<a href="{user_link(user)}">{escape(first_name(user))}</a>'
    return escape(mask_name(user))


def review_post(review: Review, user: User | None, order: Order | None) -> tuple[str, list[dict]]:
    parts = ["⭐" * review.rating, " ", Bold("Новый отзыв"), "\n\n"]
    if review.text:
        parts += [Italic(f"«{review.text.strip()}»"), "\n\n"]
    if settings.get("reviews_names") == "link" and user and user.username:
        parts += ["👤 ", TextLink(first_name(user), url=user_link(user))]
    else:
        parts += ["👤 ", mask_name(user)]
    if order:
        parts += ["\n📦 ", kind_plain(order.kind)]
    text, ents = Text(*parts).render()
    return text, [e.model_dump(exclude_none=True) for e in ents]


def reviews_target() -> str:
    return config.reviews_channel_id
