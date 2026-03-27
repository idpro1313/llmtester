from __future__ import annotations

# GRACE[M-APP][ASGI][BLOCK_AppFactory]
# CONTRACT: create_app() — FastAPI, middleware, роутеры pages + /api/*, /static; lifespan — схема БД, сиды, Fernet, планировщик.

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.access_logging import setup_access_logging
from app.bootstrap import ensure_schema, seed_if_empty
from app.config import get_session_secret, get_settings
from app.crypto_util import init_fernet_from_db
from app.db import get_session_local
from app.middleware.request_log import RequestLogMiddleware
from app.routers import api_metrics, api_providers, api_scheduler, pages

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    setup_access_logging()
    ensure_schema()
    SessionLocal = get_session_local()
    db = SessionLocal()
    try:
        seed_if_empty(db)
        init_fernet_from_db(db)
    finally:
        db.close()

    from app.scheduler import start_scheduler_from_db

    start_scheduler_from_db()
    logger.info("Приложение запущено")
    yield
    from app.scheduler import shutdown_scheduler

    shutdown_scheduler()


def create_app() -> FastAPI:
    get_settings()
    app = FastAPI(title="LLM Inference Monitor", lifespan=lifespan)
    # Сначала регистрируем внутренний слой, чтобы SessionMiddleware обрабатывал запрос раньше и session был в логе.
    app.add_middleware(RequestLogMiddleware)
    app.add_middleware(SessionMiddleware, secret_key=get_session_secret(), max_age=86400 * 7)
    app.include_router(pages.router)
    app.include_router(api_metrics.router, prefix="/api")
    app.include_router(api_providers.router, prefix="/api")
    app.include_router(api_scheduler.router, prefix="/api")
    static_dir = Path(__file__).resolve().parent / "static"
    static_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
    return app


app = create_app()
