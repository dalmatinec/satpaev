from aiogram import Router

from . import dev, exchange, gifts, my_orders, referral, start, stars, support, usernames
from .admin import build_router as build_admin_router


def build_routers() -> list[Router]:
    # порядок важен: админка, затем сценарии клиента, в конце поддержка (ловит всё остальное)
    return [
        build_admin_router(),
        start.router,
        stars.router,
        gifts.router,
        usernames.router,
        exchange.router,
        dev.router,
        my_orders.router,
        referral.router,
        support.router,
    ]
