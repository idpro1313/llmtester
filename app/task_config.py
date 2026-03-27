"""Парсинг и ограничение JSON task_config_json для целей мониторинга."""

from __future__ import annotations

# GRACE[M-SVC-PROBE][DOMAIN][BLOCK_TaskConfig]
# CONTRACT: только известные ключи; лимиты длины для безопасности и размера логов.

import json
from typing import Any

MAX_JSON_BYTES = 65536
MAX_EMBED_INPUT = 32000
MAX_RERANK_QUERY = 8000
MAX_RERANK_DOC = 16000
MAX_RERANK_DOCS = 64


class TaskConfigError(ValueError):
    pass


def parse_and_sanitize_task_config(raw: str | None) -> dict[str, Any]:
    s = (raw or "").strip()
    if not s:
        return {}
    b = s.encode("utf-8")
    if len(b) > MAX_JSON_BYTES:
        raise TaskConfigError("JSON конфигурации не длиннее 64 КБ (UTF-8).")
    try:
        d = json.loads(s)
    except json.JSONDecodeError as e:
        raise TaskConfigError(f"Некорректный JSON: {e}") from e
    if not isinstance(d, dict):
        raise TaskConfigError("Корень JSON должен быть объектом { ... }.")
    return _sanitize(d)


def _sanitize(d: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if "embedding_input" in d and isinstance(d["embedding_input"], str):
        out["embedding_input"] = d["embedding_input"][:MAX_EMBED_INPUT]
    if "rerank_query" in d and isinstance(d["rerank_query"], str):
        out["rerank_query"] = d["rerank_query"][:MAX_RERANK_QUERY]
    if "rerank_documents" in d and isinstance(d["rerank_documents"], list):
        docs = [str(x)[:MAX_RERANK_DOC] for x in d["rerank_documents"][:MAX_RERANK_DOCS]]
        out["rerank_documents"] = docs
    if "rerank_top_n" in d:
        try:
            n = int(d["rerank_top_n"])
            out["rerank_top_n"] = max(1, min(100, n))
        except (TypeError, ValueError):
            pass
    if "rerank_path" in d and isinstance(d["rerank_path"], str):
        p = d["rerank_path"].strip()
        if p and len(p) <= 256:
            out["rerank_path"] = p
    if "audio_duration_s" in d:
        try:
            f = float(d["audio_duration_s"])
            out["audio_duration_s"] = max(0.2, min(60.0, f))
        except (TypeError, ValueError):
            pass
    if "audio_language" in d and isinstance(d["audio_language"], str):
        lang = d["audio_language"].strip()[:16]
        if lang:
            out["audio_language"] = lang
    return out


def task_config_json_dumps(cfg: dict[str, Any]) -> str:
    return json.dumps(cfg, ensure_ascii=False, separators=(",", ":"))
