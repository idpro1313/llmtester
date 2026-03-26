"""Логирование входящих HTTP-запросов (метод, путь, статус, время, клиент)."""

from __future__ import annotations

import logging
import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.access_logging import ACCESS_LOGGER_NAME

_log = logging.getLogger(ACCESS_LOGGER_NAME)

# Не засоряем лог шумом (статика и проверки живости).
_SKIP_PATH_PREFIXES = ("/static/",)
_SKIP_PATHS = frozenset({"/health", "/favicon.ico"})


class RequestLogMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        path = request.url.path
        if path in _SKIP_PATHS or any(path.startswith(p) for p in _SKIP_PATH_PREFIXES):
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
