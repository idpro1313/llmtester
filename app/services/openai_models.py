"""Список моделей через OpenAI-compatible GET /v1/models (исходящий HTTP + запись в access-лог)."""

from __future__ import annotations

import json
import logging
import time

import httpx

from app.access_logging import ACCESS_LOGGER_NAME
from app.middleware.body_log import body_bytes_to_log_line

_log = logging.getLogger(ACCESS_LOGGER_NAME)


def models_endpoint_url(base_url: str) -> str:
    """Полный URL запроса списка моделей (base_url из настроек провайдера + /models)."""
    return f"{base_url.rstrip('/')}/models"


def _message_from_error_body(body: bytes, status: int) -> str:
    if not body:
        return f"HTTP {status}"
    try:
        j = json.loads(body.decode("utf-8"))
        if isinstance(j, dict):
            err = j.get("error")
            if isinstance(err, dict) and err.get("message"):
                return str(err["message"])
            if isinstance(err, str):
                return err
    except (json.JSONDecodeError, UnicodeDecodeError):
        pass
    return body[:800].decode("utf-8", errors="replace") or f"HTTP {status}"


def list_model_ids(base_url: str, api_key: str) -> tuple[list[str], str | None]:
    """
    Возвращает (отсортированные уникальные id моделей, None) или ([], сообщение_об_ошибке).
    Исходящий запрос пишется в тот же лог, что и входящие HTTP (requests.log).
    """
    url = models_endpoint_url(base_url)
    timeout = httpx.Timeout(connect=8.0, read=22.0, write=10.0, pool=5.0)
    t0 = time.perf_counter()
    _log.info("upstream begin GET %s (таймауты httpx: connect=8s read=22s)", url)
    try:
        with httpx.Client(timeout=timeout) as client:
            r = client.get(
                url,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Accept": "application/json",
                },
            )
        ms = (time.perf_counter() - t0) * 1000.0
        ct = r.headers.get("content-type")
        body = r.content
        _log.info("upstream GET %s %s %.1fms", url, r.status_code, ms)
        _log.info("  upstream_req: [Authorization: Bearer ***]")
        _log.info("  upstream_resp: %s", body_bytes_to_log_line(body, ct))

        if r.status_code >= 400:
            detail = _message_from_error_body(body, r.status_code)
            return [], f"{detail} (запрос: {url})"

        try:
            data = r.json()
        except json.JSONDecodeError as e:
            return [], f"Некорректный JSON в ответе от {url}: {e}"

        raw: list[str] = []
        for item in data.get("data") or []:
            if isinstance(item, dict) and item.get("id"):
                raw.append(str(item["id"]))
        ids = sorted(set(raw), key=str.lower)
        return ids, None

    except httpx.TimeoutException as e:
        ms = (time.perf_counter() - t0) * 1000.0
        _log.info("upstream GET %s timeout after %.1fms: %s", url, ms, e)
        return [], (
            f"Таймаут при запросе к {url} ({type(e).__name__}: {e}). "
            "Проверьте base URL провайдера (обычно заканчивается на /v1), сеть и доступность API."
        )
    except httpx.RequestError as e:
        ms = (time.perf_counter() - t0) * 1000.0
        _log.info("upstream GET %s request error after %.1fms: %s", url, ms, e)
        return [], f"{type(e).__name__}: {e} (запрос: {url})"
    except Exception as e:  # noqa: BLE001
        ms = (time.perf_counter() - t0) * 1000.0
        _log.info("upstream GET %s error after %.1fms: %s", url, ms, e)
        return [], f"{type(e).__name__}: {e} (запрос: {url})"
