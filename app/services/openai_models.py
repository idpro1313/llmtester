"""Список моделей через OpenAI-compatible GET /v1/models."""

from __future__ import annotations

import httpx
from openai import APIError, OpenAI


def list_model_ids(base_url: str, api_key: str) -> tuple[list[str], str | None]:
    """
    Возвращает (отсортированные уникальные id моделей, None) или ([], сообщение_об_ошибке).
    Короткие таймауты, без ретраев — иначе UI «висит» на медленных/немых API.
    """
    url = base_url.rstrip("/")
    timeout = httpx.Timeout(connect=8.0, read=22.0, write=10.0, pool=5.0)
    try:
        client = OpenAI(
            base_url=url,
            api_key=api_key,
            timeout=timeout,
            max_retries=0,
        )
        resp = client.models.list()
        raw = [m.id for m in resp.data if getattr(m, "id", None)]
        ids = sorted(set(raw), key=str.lower)
        return ids, None
    except APIError as e:
        body = getattr(e, "body", None)
        msg = str(body) if body else str(e)
        return [], msg
    except httpx.TimeoutException:
        return [], (
            "Таймаут при запросе списка моделей (проверьте base URL и доступность API). "
            "Введите имя модели вручную."
        )
    except Exception as e:  # noqa: BLE001 — отдаём текст в UI
        return [], str(e)
