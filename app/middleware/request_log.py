"""Логирование входящих HTTP-запросов (метод, путь, статус, время, клиент).

Для путей /api/ дополнительно пишутся строки с телом запроса и ответа (с обрезкой и маскированием секретов).
"""

from __future__ import annotations

import logging
import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.access_logging import ACCESS_LOGGER_NAME
from app.middleware.body_log import body_bytes_to_log_line

_log = logging.getLogger(ACCESS_LOGGER_NAME)

_SKIP_PATH_PREFIXES = ("/static/",)
_SKIP_PATHS = frozenset({"/health", "/favicon.ico"})
_API_PREFIX = "/api/"


class RequestLogMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        path = request.url.path
        if path in _SKIP_PATHS or any(path.startswith(p) for p in _SKIP_PATH_PREFIXES):
            return await call_next(request)

        t0 = time.perf_counter()
        status = 500
        is_api = path.startswith(_API_PREFIX)
        req_line = "-"
        resp_line = "-"

        if is_api:
            req_ct = request.headers.get("content-type")
            if request.method in ("POST", "PUT", "PATCH", "DELETE"):
                body = await request.body()

                async def receive():
                    return {"type": "http.request", "body": body, "more_body": False}

                request = Request(request.scope, receive)
                req_line = body_bytes_to_log_line(body, req_ct)
            elif request.method == "GET" and request.url.query:
                q_bytes = request.url.query.encode("utf-8", errors="replace")
                req_line = body_bytes_to_log_line(q_bytes, "application/x-www-form-urlencoded")

        try:
            response = await call_next(request)
            status = response.status_code
            if is_api:
                chunks: list[bytes] = []
                async for part in response.body_iterator:
                    chunks.append(part)
                resp_body = b"".join(chunks)
                resp_ct = response.headers.get("content-type")
                resp_line = body_bytes_to_log_line(resp_body, resp_ct)
                hdrs = {
                    k: v
                    for k, v in response.headers.items()
                    if k.lower() not in ("content-length", "transfer-encoding")
                }
                response = Response(
                    content=resp_body,
                    status_code=response.status_code,
                    headers=hdrs,
                    media_type=response.media_type,
                    background=response.background,
                )
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
            summary = "%s %s %s %.1fms ip=%s%s" % (
                request.method,
                path,
                status,
                ms,
                client,
                extra,
            )
            if is_api:
                _log.info(summary)
                _log.info("  req: %s", req_line)
                _log.info("  resp: %s", resp_line)
            else:
                _log.info(summary)
