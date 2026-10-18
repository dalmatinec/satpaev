import asyncio
import logging

from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from ..config import config
from .models import Base

log = logging.getLogger(__name__)

SessionMaker = async_sessionmaker[AsyncSession]


# Точечные изменения схемы, которые нельзя сделать добавлением колонки. Безопасно повторять.
PG_MIGRATIONS = [
    "ALTER TABLE reviews ALTER COLUMN order_id DROP NOT NULL",
]


def _sync_schema(conn) -> None:
    """Создаёт таблицы, а в существующие добавляет недостающие колонки и индексы.

    Это лёгкая автомиграция: новые поля в моделях появляются в базе сами
    после перезапуска, без ручных ALTER TABLE.
    """
    Base.metadata.create_all(conn)
    insp = inspect(conn)
    dialect = conn.dialect
    for table in Base.metadata.sorted_tables:
        existing = {c["name"] for c in insp.get_columns(table.name)}
        for column in table.columns:
            if column.name in existing:
                continue
            col_type = column.type.compile(dialect=dialect)
            sql = f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" {col_type}'
            if column.server_default is not None:
                sql += f" DEFAULT {column.server_default.arg.text}"
            conn.exec_driver_sql(sql)
            log.info("Добавлена колонка %s.%s", table.name, column.name)
        index_names = {i["name"] for i in insp.get_indexes(table.name)}
        for index in table.indexes:
            if index.name not in index_names:
                index.create(conn, checkfirst=True)
                log.info("Добавлен индекс %s", index.name)
    if dialect.name == "postgresql":
        for statement in PG_MIGRATIONS:
            conn.exec_driver_sql(statement)


async def init_db() -> tuple[AsyncEngine, SessionMaker]:
    kwargs: dict = {}
    if config.is_postgres:
        kwargs = dict(pool_size=5, max_overflow=5, pool_pre_ping=True, pool_recycle=1800)
    engine = create_async_engine(config.db_url, **kwargs)
    for attempt in range(1, 31):
        try:
            async with engine.begin() as conn:
                await conn.run_sync(_sync_schema)
            break
        except Exception as e:  # база ещё стартует
            if attempt == 30:
                raise
            log.warning("База недоступна (%s), попытка %s", e.__class__.__name__, attempt)
            await asyncio.sleep(2)
    return engine, async_sessionmaker(engine, expire_on_commit=False)
