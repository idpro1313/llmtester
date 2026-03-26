"""Сериализация дат для API: SQLite часто отдаёт naive UTC — без суффикса зона браузер трактует строку как локальное время."""

from __future__ import annotations

from datetime import datetime, timezone


def iso_utc_z(dt: datetime) -> str:
    """ISO 8601 в UTC с суффиксом Z (однозначно для Date.parse и МСК на дашборде)."""
    if dt.tzinfo is None:
        u = dt.replace(tzinfo=timezone.utc)
    else:
        u = dt.astimezone(timezone.utc)
    return u.isoformat().replace("+00:00", "Z")
