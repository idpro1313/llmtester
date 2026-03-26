"""Файловый лог HTTP-запросов (ротация) + дублирование в stdout."""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler

from app.local_secrets import monitor_data_dir

ACCESS_LOGGER_NAME = "app.http_access"
_MAX_BYTES = 5 * 1024 * 1024
_BACKUP_COUNT = 5


def _access_formatter() -> logging.Formatter:
    return logging.Formatter(
        "%(asctime)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def setup_access_logging() -> None:
    """Вызывать один раз при старте приложения (lifespan)."""
    log = logging.getLogger(ACCESS_LOGGER_NAME)
    if log.handlers:
        return
    log.setLevel(logging.INFO)
    log.propagate = False
    fmt = _access_formatter()
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    log.addHandler(sh)
    try:
        monitor_data_dir().mkdir(parents=True, exist_ok=True)
        path = monitor_data_dir() / "requests.log"
        fh = RotatingFileHandler(
            path,
            maxBytes=_MAX_BYTES,
            backupCount=_BACKUP_COUNT,
            encoding="utf-8",
        )
        fh.setFormatter(fmt)
        log.addHandler(fh)
    except OSError as e:
        logging.getLogger(__name__).warning("Не удалось создать файл requests.log: %s", e)


def clear_requests_log_files() -> str | None:
    """
    Закрывает файловый хендлер access-лога, удаляет requests.log и ротированные куски,
    создаёт пустой requests.log снова. StreamHandler не трогаем.
    Возвращает текст ошибки или None при успехе.
    """
    log = logging.getLogger(ACCESS_LOGGER_NAME)
    fmt: logging.Formatter | None = None
    for h in list(log.handlers):
        if isinstance(h, RotatingFileHandler):
            if fmt is None and h.formatter is not None:
                fmt = h.formatter
            h.flush()
            h.close()
            log.removeHandler(h)

    base = monitor_data_dir()
    names = ["requests.log"] + [f"requests.log.{i}" for i in range(1, _BACKUP_COUNT + 1)]
    try:
        for name in names:
            p = base / name
            if p.is_file():
                p.unlink()
    except OSError as e:
        return str(e)

    try:
        base.mkdir(parents=True, exist_ok=True)
        path = base / "requests.log"
        fh = RotatingFileHandler(
            path,
            maxBytes=_MAX_BYTES,
            backupCount=_BACKUP_COUNT,
            encoding="utf-8",
        )
        fh.setFormatter(fmt if fmt is not None else _access_formatter())
        log.addHandler(fh)
    except OSError as e:
        return str(e)
    return None
