"""Обрезка, маскирование и форматирование тел HTTP для access-лога (префикс /api/)."""

from __future__ import annotations

import json
import re
from typing import Any

# В лог не попадает больше стольки байт на запрос/ответ (защита от гигантских JSON вроде /metrics/series).
MAX_LOG_BODY_BYTES = 16_384

_SENSITIVE_KEY = re.compile(
    r"(password|passwd|secret|api[_-]?key|token|authorization|auth|cookie|session)",
    re.I,
)


def _redact_json(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {
            k: ("***" if _SENSITIVE_KEY.search(str(k)) else _redact_json(v))
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [_redact_json(x) for x in obj]
    return obj


def body_bytes_to_log_line(raw: bytes, content_type: str | None) -> str:
    """
    Текст одной строки лога: UTF-8, маскирование JSON, обрезка по байтам.
    Пустое тело → «-».
    """
    if not raw:
        return "-"
    ct = (content_type or "").lower()
    if "multipart/" in ct:
        return "[multipart/form-data не логируется]"
    total = len(raw)
    truncated = total > MAX_LOG_BODY_BYTES
    chunk = raw if not truncated else raw[:MAX_LOG_BODY_BYTES]
    s = chunk.decode("utf-8", errors="replace")
    if not truncated and ("json" in ct or s.lstrip().startswith(("{", "["))):
        try:
            j = json.loads(s)
            s = json.dumps(_redact_json(j), ensure_ascii=False)
        except json.JSONDecodeError:
            pass
    if truncated:
        s = f"{s} …[обрезано, всего {total} байт]"
    return s.replace("\n", "\\n").replace("\r", "\\r")
