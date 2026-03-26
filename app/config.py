import os
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Настройки из переменных окружения (файл .env не используется)."""

    model_config = SettingsConfigDict(env_file=None, extra="ignore")

    database_url: str = "sqlite:///./data/monitor.db"
    fernet_key: str = ""
    """Необязательно: переопределение ключа Fernet; иначе ключ в БД (app_crypto_state)."""


def get_session_secret() -> str:
    """Секрет подписи cookie: SESSION_SECRET из env или файл в каталоге данных."""
    v = (os.environ.get("SESSION_SECRET") or "").strip()
    if v:
        return v
    from app.local_secrets import ensure_session_secret_file

    return ensure_session_secret_file()


@lru_cache
def get_settings() -> Settings:
    return Settings()


def sqlalchemy_url() -> str:
    url = get_settings().database_url
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url
