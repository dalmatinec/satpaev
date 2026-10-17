from aiogram import Bot
from aiogram.utils.formatting import Bold, Italic, Text

from ..cb import Shop
from ..config import config
from ..db.models import Order, Review, User
from ..ui import btn, kb, send_safe
from .orders import kind_name


async def ask_review(bot: Bot, order: Order) -> None:
    stars = [btn("⭐" * n, Shop(sec="rev", a="rate", i=order.id, v=str(n))) for n in range(1, 6)]
    await send_safe(
        bot,
        order.user_id,
        f"🙏 Оцените, пожалуйста, заказ <b>#{order.id}</b>. Это займёт пару секунд и очень нам поможет.",
        kb(stars[4:5], stars[3:4], stars[:3]),
    )


def mask_name(user: User | None) -> str:
    name = (user.full_name if user else "") or "Клиент"
    name = name.split()[0]
    if len(name) <= 2:
        return name[0] + "*"
    return name[:2] + "*" * min(3, len(name) - 2)


def review_post(review: Review, user: User | None, order: Order | None) -> tuple[str, list[dict]]:
    parts = ["⭐" * review.rating, " ", Bold("Новый отзыв"), "\n\n"]
    if review.text:
        parts += [Italic(f"«{review.text.strip()}»"), "\n\n"]
    parts += ["👤 ", mask_name(user)]
    if order:
        parts += ["\n📦 ", kind_name(order.kind)]
    text, ents = Text(*parts).render()
    return text, [e.model_dump(exclude_none=True) for e in ents]


def reviews_target() -> str:
    return config.reviews_channel_id
