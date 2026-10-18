"""Админка: сайт и Telegram Web App."""

import time

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from ...cb import Adm
from ...config import config
from ...services import settings, webapp
from ...ui import answer, btn, kb, show
from ...utils import h
from .common import Ctx, ask, op, screen

router = Router(name="admin_site")


def _api_line() -> str:
    from ... import web_api

    st = web_api.STATS
    if not config.api_port:
        return "⚪ выключен (нет API_PORT в docker-compose.yml)"
    if not st["running"]:
        return "🔴 не запустился: " + h(st["error"] or "перезапустите бота")
    if not st["last"]:
        return f"🟡 работает на порту {st['port']}, но сайт ещё ни разу не обращался"
    ago = int(time.time() - st["last"])
    when = f"{ago} с назад" if ago < 120 else f"{ago // 60} мин назад" if ago < 7200 else f"{ago // 3600} ч назад"
    return f"🟢 работает, запросов за сутки: <b>{web_api.hits()}</b>, последний {when}"


@screen("web")
async def web_view(target, session: AsyncSession, cbd: Adm, note: str = "") -> None:
    site = str(settings.get("site_url") or "")
    on = bool(settings.get("webapp_enabled"))
    if not site:
        app_line = "нужна ссылка сайта"
    elif not site.startswith("https://"):
        app_line = "⚠️ нужна ссылка с https://, сейчас сайт откроется в браузере"
    else:
        app_line = "🟢 вкл" if on else "⚪ выкл, сайт откроется в браузере"
    text = (
        "🌐 <b>Сайт и Web App</b>\n\n"
        f"🔗 Сайт: {h(site) or 'не задан'}\n"
        f"🔌 Связь с сайтом: {_api_line()}\n"
        f"📱 Web App: {app_line}\n"
        f"🏷 Кнопка у поля ввода: «{h(settings.get('webapp_menu_text') or 'Открыть')}»\n\n"
        "Сайт сам берёт из бота курсы (💱 Курсы), цены звёзд (⭐ Звёзды), минимальный заказ и тексты. "
        "Изменения появляются на сайте в течение минуты.\n\n"
        "Web App: кнопка слева от поля ввода и «🌐 Наш сайт» в меню открывают сайт прямо внутри Telegram. "
        "Название и цвет кнопки в меню: 🔘 Кнопки и экраны → Главное меню."
        + (f"\n\n{note}" if note else "")
    )
    await show(target, text, kb(
        [btn("✏️ Тексты сайта", Adm(s="tx", a="grp", v="site")), btn("🔗 Ссылка сайта", Adm(s="web", a="url"))],
        [btn(("🟢" if on else "⚪") + " Web App", Adm(s="web", a="toggle")),
         btn("🏷 Кнопка у поля ввода", Adm(s="web", a="menu"))],
        [btn("🔄 Обновить", Adm(s="web", a="apply"))],
        [btn("◀️ Ещё", Adm(s="more"))],
    ))


@router.callback_query(Adm.filter(F.s == "web"))
async def on_web(cb: CallbackQuery, callback_data: Adm, session: AsyncSession, state: FSMContext) -> None:
    a, back = callback_data.a, Adm(s="web")
    if a == "url":
        await ask(cb, state, "set_url", "🔗 Пришлите ссылку сайта, например <code>https://satboxcom.duckdns.org</code>.\n"
                  "Для Web App нужна ссылка с https. «Пропустить» уберёт ссылку.", back, skip=True, key="site_url")
        return
    if a == "menu":
        await ask(cb, state, "web_menu", "🏷 Как подписать кнопку слева от поля ввода? Коротко, например "
                  "<code>Открыть</code> или <code>SatBox</code>:", back)
        return
    note = ""
    if a == "toggle":
        await settings.put(session, "webapp_enabled", not settings.get("webapp_enabled"))
        await session.commit()
    if a in ("toggle", "apply"):
        err = await webapp.apply(cb.bot)
        note = f"⚠️ Telegram не принял кнопку: {h(err)}" if err else "✅ Кнопка обновлена. Если не видно, перезайдите в чат с ботом."
    await answer(cb)
    await web_view(cb, session, back, note)


@op("web_menu")
async def op_web_menu(ctx: Ctx) -> None:
    value = (ctx.text or "").strip()
    if not value:
        await ctx.target.answer("Пришлите текст кнопки:")
        return
    await settings.put(ctx.session, "webapp_menu_text", value[:32])
    await ctx.session.commit()
    await webapp.apply(ctx.bot)
    await ctx.back()
