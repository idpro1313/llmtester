from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.bootstrap import ensure_schema, seed_if_empty
from app.config import get_session_secret, get_settings
from app.crypto_util import init_fernet_from_db
from app.db import get_session_local
from app.routers import api_metrics, api_providers, pages

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
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
    app.add_middleware(SessionMiddleware, secret_key=get_session_secret(), max_age=86400 * 7)
    app.include_router(pages.router)
    app.include_router(api_metrics.router, prefix="/api")
    app.include_router(api_providers.router, prefix="/api")
    static_dir = Path(__file__).resolve().parent / "static"
    static_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
    return app


app = create_app()
