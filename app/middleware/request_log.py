"""Логирование входящих HTTP-запросов (метод, путь, статус, время, клиент).

Не пишутся: /api/*, /static/*, типовые GET страниц UI (дашборд, /admin/*, логин и т.д.).
POST/DELETE к админке остаются в логе. Исходящие вызовы к провайдерам — отдельные строки upstream.
"""

from __future__ import annotations

import logging
import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.access_logging import ACCESS_LOGGER_NAME

_log = logging.getLogger(ACCESS_LOGGER_NAME)

_SKIP_PATH_PREFIXES = ("/static/", "/api/")
_SKIP_PATHS = frozenset({"/health", "/favicon.ico", "/api"})
# GET к «просмотру» страниц не засоряют лог; изменения — POST (и редкие GET вне списка).
_SKIP_GET_PATHS = frozenset({"/", "/dashboard", "/dashboard/charts", "/login", "/setup", "/logout"})
_ADMIN_PREFIX = "/admin/"


def _skip_request_log(request: Request, path: str) -> bool:
    if path in _SKIP_PATHS or any(path.startswith(p) for p in _SKIP_PATH_PREFIXES):
        return True
    if request.method == "GET" and path in _SKIP_GET_PATHS:
        return True
    if request.method == "GET" and path.startswith(_ADMIN_PREFIX):
        return True
    return False


class RequestLogMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        path = request.url.path
        if _skip_request_log(request, path):
            return await call_next(request)

        t0 = time.perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            return response
        except Exception:
            status = 500
            raise
        finally:
            ms = (time.perf_counter() - t0) * 1000.0
            client = request.client.host if request.client else "-"
            uid = None
            if hasattr(request, "session"):
                try:
                    uid = request.session.get("admin_user_id")
                except (AttributeError, KeyError, TypeError):
                    uid = None
            extra = f" user_id={uid}" if uid else ""
            _log.info(
                "%s %s %s %.1fms ip=%s%s",
                request.method,
                path,
                status,
                ms,
                client,
                extra,
            )
