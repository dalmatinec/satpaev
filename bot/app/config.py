import os
from dataclasses import dataclass
from zoneinfo import ZoneInfo

from sqlalchemy.engine import URL, make_url


def _ids(value: str) -> tuple[int, ...]:
    out = []
    for part in value.replace(" ", "").split(","):
        if part.lstrip("-").isdigit():
            out.append(int(part))
    return tuple(out)


def _db_url() -> URL:
    raw = os.getenv("DATABASE_URL", "").strip()
    if raw:
        return make_url(raw)
    return URL.create(
        "postgresql+asyncpg",
        username=os.getenv("POSTGRES_USER", "satpaev"),
        password=os.getenv("POSTGRES_PASSWORD", ""),
        host=os.getenv("DB_HOST", "db"),
        port=int(os.getenv("DB_PORT", "5432")),
        database=os.getenv("POSTGRES_DB", "satpaev"),
    )


@dataclass(frozen=True, slots=True)
class Config:
    bot_token: str
    admin_ids: tuple[int, ...]
    brand: str
    tz: ZoneInfo
    db_url: URL
    redis_url: str
    channel_id: str
    reviews_channel_id: str
    poster_enabled: bool
    site_url: str
    backup_dir: str
    backup_time: str
    backup_keep: int
    shared_dir: str

    @property
    def owner_id(self) -> int:
        return self.admin_ids[0] if self.admin_ids else 0

    @property
    def is_postgres(self) -> bool:
        return self.db_url.get_backend_name() == "postgresql"


def load() -> Config:
    channel = os.getenv("CHANNEL_ID", "").strip()
    return Config(
        bot_token=os.getenv("BOT_TOKEN", "").strip(),
        admin_ids=_ids(os.getenv("ADMIN_IDS", "")),
        brand=os.getenv("BRAND_NAME", "Satpaev").strip() or "Satpaev",
        tz=ZoneInfo(os.getenv("TZ", "Asia/Almaty") or "Asia/Almaty"),
        db_url=_db_url(),
        redis_url=os.getenv("REDIS_URL", "").strip(),
        channel_id=channel,
        reviews_channel_id=os.getenv("REVIEWS_CHANNEL_ID", "").strip() or channel,
        poster_enabled=bool(os.getenv("TG_API_ID", "").strip() and os.getenv("TG_API_HASH", "").strip()),
        site_url=os.getenv("SITE_URL", "").strip(),
        backup_dir=os.getenv("BACKUP_DIR", "/backups"),
        backup_time=os.getenv("BACKUP_TIME", "04:00").strip() or "04:00",
        backup_keep=max(1, int(os.getenv("BACKUP_KEEP", "1") or 1)),
        shared_dir=os.getenv("SHARED_DIR", "/shared"),
    )


config = load()
