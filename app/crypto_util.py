import logging
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import AppCryptoState

log = logging.getLogger(__name__)

_fernet_key_cache: Optional[str] = None


def init_fernet_from_db(db: Session) -> None:
    """
    При старте приложения: взять ключ из FERNET_KEY (env) или из БД, иначе сгенерировать и сохранить (id=1).
    """
    global _fernet_key_cache
    env_key = (get_settings().fernet_key or "").strip()
    if env_key:
        _fernet_key_cache = env_key
        log.info("Используется FERNET_KEY из окружения.")
        return

    row = db.get(AppCryptoState, 1)
    if row is not None:
        _fernet_key_cache = row.fernet_key
        return

    raw = Fernet.generate_key().decode("ascii")
    try:
        db.add(AppCryptoState(id=1, fernet_key=raw))
        db.commit()
        _fernet_key_cache = raw
        log.info("Создан и сохранён в БД ключ шифрования Fernet (таблица app_crypto_state).")
    except IntegrityError:
        db.rollback()
        row = db.get(AppCryptoState, 1)
        if row is None:
            raise
        _fernet_key_cache = row.fernet_key


def _fernet() -> Fernet:
    if not _fernet_key_cache:
        raise RuntimeError(
            "Ключ Fernet не инициализирован. Должен вызываться init_fernet_from_db при старте приложения."
        )
    return Fernet(_fernet_key_cache.encode("ascii"))


def encrypt_secret(plain: str) -> str:
    if not plain:
        return ""
    return _fernet().encrypt(plain.encode("utf-8")).decode("ascii")


def decrypt_secret(token: str) -> str:
    if not token:
        return ""
    try:
        return _fernet().decrypt(token.encode("ascii")).decode("utf-8")
    except InvalidToken:
        return ""
