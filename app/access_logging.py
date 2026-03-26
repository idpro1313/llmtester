"""Файловый лог HTTP-запросов (ротация) + дублирование в stdout."""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler

from app.local_secrets import monitor_data_dir

ACCESS_LOGGER_NAME = "app.http_access"
_MAX_BYTES = 5 * 1024 * 1024
_BACKUP_COUNT = 5


def setup_access_logging() -> None:
    """Вызывать один раз при старте приложения (lifespan)."""
    log = logging.getLogger(ACCESS_LOGGER_NAME)
    if log.handlers:
        return
    log.setLevel(logging.INFO)
    log.propagate = False
    fmt = logging.Formatter(
        "%(asctime)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
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
