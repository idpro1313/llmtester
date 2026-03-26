"""Файлы секретов рядом с БД (каталог data / MONITOR_DATA_DIR)."""

from __future__ import annotations

import os
import secrets
from pathlib import Path


def monitor_data_dir() -> Path:
    return Path(os.environ.get("MONITOR_DATA_DIR", "data"))


def ensure_session_secret_file() -> str:
    """Читает или создаёт data/.session_secret (в Docker: /app/data/.session_secret)."""
    base = monitor_data_dir()
    base.mkdir(parents=True, exist_ok=True)
    path = base / ".session_secret"
    if path.is_file():
        text = path.read_text(encoding="utf-8").strip()
        if text:
            return text
    token = secrets.token_urlsafe(48)
    path.write_text(token, encoding="utf-8")
    return token
