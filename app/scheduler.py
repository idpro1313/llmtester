from __future__ import annotations

import logging
from typing import Any, Optional

from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy.orm import Session

from app.db import get_session_local
from app.models import GlobalSettings
from app.services.probe import run_all_enabled_probes

log = logging.getLogger(__name__)

JOB_ID = "inference_probes"
_scheduler: Optional[BackgroundScheduler] = None
"""Пользователь остановил автозамеры (pause); после смены интервала в настройках пауза сохраняется."""
_probes_job_paused: bool = False


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


def _pause_job_if_present(sch: BackgroundScheduler) -> None:
    if sch.get_job(JOB_ID):
        try:
            sch.pause_job(JOB_ID)
        except Exception:
            log.exception("pause_job(%s)", JOB_ID)


def reschedule_from_db() -> None:
    was_paused = _probes_job_paused
    sch = attach_scheduler()
    if not sch.running:
        start_scheduler_from_db()
        if was_paused:
            _pause_job_if_present(sch)
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
    if was_paused:
        _pause_job_if_present(sch)
    log.info("Планировщик перенастроен: интервал %s с", interval)


def shutdown_scheduler() -> None:
    global _scheduler
    if _scheduler is not None and _scheduler.running:
        _scheduler.shutdown(wait=False)
    _scheduler = None


def pause_scheduled_probes() -> None:
    """Остановить периодические замеры (pause job)."""
    global _probes_job_paused
    sch = _scheduler
    if sch and sch.running and sch.get_job(JOB_ID):
        _pause_job_if_present(sch)
    _probes_job_paused = True
    log.info("Автозамеры приостановлены (пауза)")


def resume_scheduled_probes() -> None:
    """Возобновить периодические замеры."""
    global _probes_job_paused
    _probes_job_paused = False
    sch = attach_scheduler()
    if not sch.running:
        start_scheduler_from_db()
        log.info("Планировщик запущен, автозамеры активны")
        return
    job = sch.get_job(JOB_ID)
    if job:
        try:
            sch.resume_job(JOB_ID)
            log.info("Автозамеры возобновлены (resume)")
        except Exception:
            log.exception("resume_job")
            start_scheduler_from_db()
    else:
        start_scheduler_from_db()
        log.info("Планировщик: задача пересоздана, автозамеры активны")


def scheduler_status_dict(db: Session) -> dict[str, Any]:
    """Состояние для API / дашборда."""
    interval = get_interval_seconds(db)
    sch = _scheduler
    sched_running = sch is not None and sch.running
    job = sch.get_job(JOB_ID) if sched_running else None
    next_iso: str | None = None
    if job is not None and job.next_run_time is not None:
        next_iso = job.next_run_time.isoformat()
    active = bool(sched_running and job is not None and not _probes_job_paused)
    return {
        "scheduler_running": sched_running,
        "job_present": job is not None,
        "job_paused": _probes_job_paused,
        "interval_seconds": interval,
        "next_run_time": None if _probes_job_paused else next_iso,
        "next_run_time_scheduled": next_iso,
        "auto_probes_active": active,
    }
