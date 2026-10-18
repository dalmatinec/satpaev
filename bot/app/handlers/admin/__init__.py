from aiogram import Router

from . import broadcast, catalog, channel, clients, common, custom, misc, orders, rates, site, stats, subs
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
        custom.router,
        subs.router,
        site.router,
    )
    return router
