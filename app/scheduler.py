from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Optional

from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy.orm import Session

from app.db import get_session_local
from app.models import GlobalSettings
from app.services.probe import run_all_enabled_probes

if TYPE_CHECKING:
    from apscheduler.schedulers.base import BaseScheduler

log = logging.getLogger(__name__)

JOB_ID = "inference_probes"
_scheduler: Optional[BackgroundScheduler] = None


def _tick() -> None:
    SessionLocal = get_session_local()
    db = SessionLocal()
    try:
        n = run_all_enabled_probes(db)
        if n:
            log.info("Завершён цикл замеров, активных целей: %s", n)
    except Exception:
        log.exception("Ошибка планировщика замеров")
    finally:
        db.close()


def get_interval_seconds(db: Session) -> int:
    gs = db.get(GlobalSettings, 1)
    if gs is None:
        return 300
    return max(30, int(gs.probe_interval_seconds))


def attach_scheduler() -> BackgroundScheduler:
    global _scheduler
    if _scheduler is not None:
        return _scheduler
    _scheduler = BackgroundScheduler(timezone="UTC")
    return _scheduler


def start_scheduler_from_db() -> None:
    sch = attach_scheduler()
    SessionLocal = get_session_local()
    db = SessionLocal()
    try:
        interval = get_interval_seconds(db)
    finally:
        db.close()
    if sch.get_job(JOB_ID):
        sch.remove_job(JOB_ID)
    sch.add_job(_tick, "interval", seconds=interval, id=JOB_ID, replace_existing=True)
    if not sch.running:
        sch.start()
    log.info("Планировщик: интервал %s с", interval)


def reschedule_from_db() -> None:
    sch = attach_scheduler()
    if not sch.running:
        start_scheduler_from_db()
        return
    SessionLocal = get_session_local()
    db = SessionLocal()
    try:
        interval = get_interval_seconds(db)
    finally:
        db.close()
    job = sch.get_job(JOB_ID)
    if job:
        sch.reschedule_job(JOB_ID, trigger="interval", seconds=interval)
    else:
        sch.add_job(_tick, "interval", seconds=interval, id=JOB_ID, replace_existing=True)
    log.info("Планировщик перенастроен: интервал %s с", interval)


def shutdown_scheduler() -> None:
    global _scheduler
    if _scheduler is not None and _scheduler.running:
        _scheduler.shutdown(wait=False)
    _scheduler = None
