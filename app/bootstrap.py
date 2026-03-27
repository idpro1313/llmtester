"""Инициализация БД и начальных данных."""

from __future__ import annotations

# GRACE[M-BOOT][PERSIST][BLOCK_SchemaSeed]
# CONTRACT: ensure_schema (create_all + migrate_engine), seed_if_empty — GlobalSettings и шаблонные Provider.

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import Base, get_engine
from app.models import GlobalSettings, Provider
from app.schema_migrate import migrate_engine
from llm_benchmark.core import DEFAULT_PROMPT


def ensure_schema() -> None:
    engine = get_engine()
    Base.metadata.create_all(bind=engine)
    migrate_engine(engine)


def seed_if_empty(db: Session) -> None:
    if db.scalar(select(GlobalSettings).where(GlobalSettings.id == 1)) is None:
        db.add(
            GlobalSettings(
                id=1,
                benchmark_prompt=DEFAULT_PROMPT,
                probe_interval_seconds=300,
                default_warmup=0,
                default_timeout=120.0,
            )
        )

    if db.scalar(select(Provider).limit(1)) is None:
        defaults = [
            ("cloud_ru", "Cloud.ru", "https://foundation-models.api.cloud.ru/v1", 0),
            ("yandex", "Yandex Cloud (Foundation Models)", "https://llm.api.cloud.yandex.net/v1", 1),
            ("mws", "MWS", "https://REPLACE-WITH-MWS-OPENAI-BASE/v1", 2),
        ]
        for slug, name, url, order in defaults:
            db.add(
                Provider(
                    slug=slug,
                    display_name=name,
                    base_url=url,
                    api_key_encrypted="",
                    is_active=False,
                    sort_order=order,
                )
            )

    db.commit()
