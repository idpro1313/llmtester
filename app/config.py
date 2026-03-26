from functools import lru_cache
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "sqlite:///./data/monitor.db"
    fernet_key: str = ""
    """Ключ Fernet (base64) для шифрования API-ключей провайдеров. Сгенерировать: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""""

    session_secret: str = "change-me-in-production"
    admin_username: str = "admin"
    admin_password: str = "admin"

    @property
    def sqlalchemy_url(self) -> str:
        url = self.database_url
        if url.startswith("postgresql://"):
            return url.replace("postgresql://", "postgresql+psycopg://", 1)
        return url


@lru_cache
def get_settings() -> Settings:
    return Settings()
