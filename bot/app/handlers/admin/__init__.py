from aiogram import Router

from . import broadcast, catalog, channel, clients, common, misc, orders, rates, stats
from .common import IsAdmin


def build_router() -> Router:
    router = Router(name="admin")
    router.message.filter(IsAdmin())
    router.callback_query.filter(IsAdmin())
    router.include_routers(
        common.router,
        orders.router,
        rates.router,
        catalog.router,
        channel.router,
        broadcast.router,
        clients.router,
        stats.router,
        misc.router,
    )
    return router
