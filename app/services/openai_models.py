"""Список моделей через OpenAI-compatible GET /v1/models."""

from __future__ import annotations

from openai import APIError, OpenAI


def list_model_ids(base_url: str, api_key: str, timeout: float = 60.0) -> tuple[list[str], str | None]:
    """
    Возвращает (отсортированные уникальные id моделей, None) или ([], сообщение_об_ошибке).
    """
    url = base_url.rstrip("/")
    try:
        client = OpenAI(base_url=url, api_key=api_key, timeout=timeout)
        resp = client.models.list()
        raw = [m.id for m in resp.data if getattr(m, "id", None)]
        ids = sorted(set(raw), key=str.lower)
        return ids, None
    except APIError as e:
        body = getattr(e, "body", None)
        msg = str(body) if body else str(e)
        return [], msg
    except Exception as e:  # noqa: BLE001 — отдаём текст в UI
        return [], str(e)
