"""Список моделей через OpenAI-compatible API (как в документации Cloud.ru: OpenAI client + base_url)."""

from __future__ import annotations

import logging
import time

import httpx
from openai import APIError, OpenAI

from app.access_logging import ACCESS_LOGGER_NAME

_log = logging.getLogger(ACCESS_LOGGER_NAME)

# Согласовано с прежними лимитами httpx: UI не «висит» на немом API.
_OPENAI_TIMEOUT = httpx.Timeout(connect=8.0, read=22.0, write=10.0, pool=5.0)


def models_endpoint_url(base_url: str) -> str:
    """Полный URL эндпоинта списка моделей (для сообщений об ошибках и UI)."""
    return f"{base_url.rstrip('/')}/models"


def list_model_ids(base_url: str, api_key: str) -> tuple[list[str], str | None]:
    """
    Возвращает (отсортированные уникальные id моделей, None) или ([], сообщение_об_ошибке).
    Вызов идёт через официальный клиент OpenAI (как у Cloud.ru), без дополнительных заголовков.
    """
    base = base_url.rstrip("/")
    url = models_endpoint_url(base_url)
    t0 = time.perf_counter()
    _log.info(
        "upstream begin OpenAI.models.list base_url=%s (клиент как в документации провайдера)",
        base,
    )
    try:
        client = OpenAI(
            api_key=api_key.strip(),
            base_url=base,
            timeout=_OPENAI_TIMEOUT,
            max_retries=0,
        )
        resp = client.models.list()
        ms = (time.perf_counter() - t0) * 1000.0
        raw = [m.id for m in resp.data if getattr(m, "id", None)]
        ids = sorted(set(raw), key=str.lower)
        _log.info(
            "upstream models.list ok %.1fms endpoint=%s count=%d",
            ms,
            url,
            len(ids),
        )
        return ids, None
    except APIError as e:
        ms = (time.perf_counter() - t0) * 1000.0
        _log.info("upstream models.list APIError after %.1fms: %s", ms, e)
        body = getattr(e, "body", None)
        msg = str(body) if body else str(e)
        return [], f"{msg} (эндпоинт: {url})"
    except httpx.TimeoutException as e:
        ms = (time.perf_counter() - t0) * 1000.0
        _log.info("upstream models.list timeout after %.1fms: %s", ms, e)
        return [], (
            f"Таймаут при запросе к {url} ({type(e).__name__}: {e}). "
            "Проверьте base URL (например https://foundation-models.api.cloud.ru/v1), сеть и доступность API."
        )
    except httpx.RequestError as e:
        ms = (time.perf_counter() - t0) * 1000.0
        _log.info("upstream models.list request error after %.1fms: %s", ms, e)
        return [], f"{type(e).__name__}: {e} (эндпоинт: {url})"
    except Exception as e:  # noqa: BLE001
        ms = (time.perf_counter() - t0) * 1000.0
        _log.info("upstream models.list error after %.1fms: %s", ms, e)
        return [], f"{type(e).__name__}: {e} (эндпоинт: {url})"
