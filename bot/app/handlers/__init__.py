from aiogram import Router

from . import chats, dev, menu_button, exchange, gifts, my_orders, referral, start, stars, subscribe, support, usernames
from .admin import build_router as build_admin_router


def build_routers() -> list[Router]:
    # порядок важен: админка, затем сценарии клиента, в конце поддержка (ловит всё остальное)
    return [
        menu_button.router,  # «🏠 Главное меню» под полем ввода работает из любого места
        build_admin_router(),
        chats.router,
        subscribe.router,
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
