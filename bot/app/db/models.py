from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    text as sql,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


FALSE = sql("false")
ZERO = sql("0")
EMPTY = sql("''")


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    username: Mapped[str | None] = mapped_column(String(64))
    full_name: Mapped[str] = mapped_column(String(256), default="", server_default=EMPTY)
    referrer_id: Mapped[int | None] = mapped_column(BigInteger)
    tag: Mapped[str] = mapped_column(String(16), default="", server_default=EMPTY)
    note: Mapped[str] = mapped_column(Text, default="", server_default=EMPTY)
    is_banned: Mapped[bool] = mapped_column(Boolean, default=False, server_default=FALSE)
    is_blocked: Mapped[bool] = mapped_column(Boolean, default=False, server_default=FALSE)
    orders_done: Mapped[int] = mapped_column(Integer, default=0, server_default=ZERO)
    total_spent: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0, server_default=ZERO)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        Index("ix_users_username", "username"),
        Index("ix_users_referrer", "referrer_id"),
        Index("ix_users_created", "created_at"),
        Index("ix_users_last_seen", "last_seen"),
        Index("ix_users_tag", "tag"),
    )

    @property
    def mention(self) -> str:
        return f"@{self.username}" if self.username else f"id{self.id}"


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(12), default="new", server_default=sql("'new'"))
    stage: Mapped[str] = mapped_column(String(16), default="", server_default=EMPTY)
    title: Mapped[str] = mapped_column(String(256), default="", server_default=EMPTY)
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    cost: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    item_id: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    done_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index("ix_orders_status_created", "status", "created_at"),
        Index("ix_orders_user_created", "user_id", "created_at"),
        Index("ix_orders_kind_done", "kind", "done_at"),
        Index("ix_orders_done", "done_at"),
    )

    @property
    def profit(self) -> Decimal | None:
        if self.amount is None or self.cost is None:
            return None
        return self.amount - self.cost


class Item(Base):
    """Каталог: подарки, готовые юзернеймы, услуги, портфолио."""

    __tablename__ = "items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(16))
    category: Mapped[str] = mapped_column(String(32), default="", server_default=EMPTY)
    title: Mapped[str] = mapped_column(String(256), default="", server_default=EMPTY)
    description: Mapped[str] = mapped_column(Text, default="", server_default=EMPTY)
    photo: Mapped[str] = mapped_column(String(256), default="", server_default=EMPTY)
    link: Mapped[str] = mapped_column(String(512), default="", server_default=EMPTY)
    price: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    price_text: Mapped[str] = mapped_column(String(512), default="", server_default=EMPTY)
    cost_ton: Mapped[Decimal | None] = mapped_column(Numeric(14, 4))
    markup: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=sql("true"))
    sort: Mapped[int] = mapped_column(Integer, default=0, server_default=ZERO)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        Index("ix_items_kind_active", "kind", "is_active", "sort", "id"),
        Index("ix_items_kind_category", "kind", "category"),
    )


class Rate(Base):
    __tablename__ = "rates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(16))
    buy: Mapped[Decimal | None] = mapped_column(Numeric(14, 4))
    sell: Mapped[Decimal | None] = mapped_column(Numeric(14, 4))
    min_qty: Mapped[Decimal | None] = mapped_column(Numeric(14, 4))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=sql("true"))
    sort: Mapped[int] = mapped_column(Integer, default=0, server_default=ZERO)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    __table_args__ = (Index("ix_rates_active", "is_active", "sort"),)


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict | list | str | int | float | bool | None] = mapped_column(JSON)


class Reminder(Base):
    __tablename__ = "reminders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("orders.id", ondelete="CASCADE"))
    text: Mapped[str] = mapped_column(Text)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    sent: Mapped[bool] = mapped_column(Boolean, default=False, server_default=FALSE)

    __table_args__ = (
        Index("ix_reminders_due", "sent", "due_at"),
        Index("ix_reminders_order", "order_id"),
    )


class SupportLink(Base):
    """Связка сообщения у админа с клиентом, чтобы отвечать реплаем."""

    __tablename__ = "support_links"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    admin_chat_id: Mapped[int] = mapped_column(BigInteger)
    admin_msg_id: Mapped[int] = mapped_column(BigInteger)
    user_id: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        Index("ux_support_admin_msg", "admin_chat_id", "admin_msg_id", unique=True),
        Index("ix_support_created", "created_at"),
    )


class RefAccrual(Base):
    __tablename__ = "ref_accruals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    referrer_id: Mapped[int] = mapped_column(BigInteger)
    referral_id: Mapped[int] = mapped_column(BigInteger)
    order_id: Mapped[int] = mapped_column(Integer)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    paid: Mapped[bool] = mapped_column(Boolean, default=False, server_default=FALSE)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        Index("ix_ref_referrer_paid", "referrer_id", "paid"),
        Index("ux_ref_order", "order_id", unique=True),
    )


class Review(Base):
    __tablename__ = "reviews"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(Integer)
    user_id: Mapped[int] = mapped_column(BigInteger)
    rating: Mapped[int] = mapped_column(SmallInteger)
    text: Mapped[str] = mapped_column(Text, default="", server_default=EMPTY)
    status: Mapped[str] = mapped_column(String(12), default="new", server_default=sql("'new'"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        Index("ux_reviews_order", "order_id", unique=True),
        Index("ix_reviews_status", "status", "created_at"),
    )


class Post(Base):
    """Очередь постов в канал. mode=account отправляет постер (Telethon), mode=bot сам бот."""

    __tablename__ = "posts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(16), default="news", server_default=sql("'news'"))
    mode: Mapped[str] = mapped_column(String(8), default="account", server_default=sql("'account'"))
    target: Mapped[str] = mapped_column(String(64))
    text: Mapped[str] = mapped_column(Text, default="", server_default=EMPTY)
    entities: Mapped[list | None] = mapped_column(JSON)
    media: Mapped[str] = mapped_column(String(256), default="", server_default=EMPTY)
    status: Mapped[str] = mapped_column(String(12), default="pending", server_default=sql("'pending'"))
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default=ZERO)
    error: Mapped[str] = mapped_column(Text, default="", server_default=EMPTY)
    remote_id: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (Index("ix_posts_status", "status", "mode", "id"),)


class PosterStatus(Base):
    __tablename__ = "poster_status"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    state: Mapped[str] = mapped_column(String(32), default="", server_default=EMPTY)
    info: Mapped[str] = mapped_column(String(256), default="", server_default=EMPTY)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
