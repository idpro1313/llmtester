"""Запуск замеров и запись в БД."""

from __future__ import annotations

# GRACE[M-SVC-PROBE][DOMAIN][BLOCK_ProbeCycles]
# CONTRACT: циклы замеров по целям, ThreadPoolExecutor по LLMTESTER_PROBE_PARALLEL; запись Measurement.

import logging
import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.access_logging import access_http_logger
from app.crypto_util import decrypt_secret
from app.db import get_session_local
from app.models import GlobalSettings, Measurement, MonitoredTarget, Provider
from llm_benchmark.core import run_probe

log = logging.getLogger(__name__)
_http_access = access_http_logger()

_manual_probe_lock = threading.Lock()
_manual_probe_running = False


def _max_parallel_probe_workers() -> int:
    raw = os.environ.get("LLMTESTER_PROBE_PARALLEL", "12").strip()
    try:
        n = int(raw, 10)
    except ValueError:
        n = 12
    return max(1, min(32, n))


def _probe_target_by_id(target_id: int) -> int:
    """
    Один поток — одна цель: своя сессия БД, независимые HTTP к API провайдера.
    Возвращает 1, если в БД сохранены строки замеров, иначе 0.
    """
    SessionLocal = get_session_local()
    db = SessionLocal()
    try:
        target = db.scalars(
            select(MonitoredTarget)
            .where(MonitoredTarget.id == target_id)
            .options(joinedload(MonitoredTarget.provider))
        ).first()
        if target is None:
            return 0
        if not target.model_name.strip():
            _http_access.info("probe | skip target_id=%s reason=empty_model_name", target_id)
            return 0
        rows = run_target_probe(db, target)
        return 1 if rows else 0
    except Exception:
        log.exception("Ошибка замера target_id=%s", target_id)
        _http_access.info("probe | error target_id=%s see app log", target_id)
        return 0
    finally:
        db.close()


def run_all_enabled_probes_in_background() -> bool:
    """
    Запускает те же замеры, что и по кнопке «сейчас», в отдельном потоке.
    Возвращает False, если предыдущий ручной запуск ещё выполняется.
    """
    global _manual_probe_running
    with _manual_probe_lock:
        if _manual_probe_running:
            return False
        _manual_probe_running = True

    def job() -> None:
        global _manual_probe_running
        try:
            SessionLocal = get_session_local()
            db = SessionLocal()
            try:
                log.info("Ручной запуск замеров в фоне…")
                n = run_all_enabled_probes(db, probe_cycle_source="manual")
                log.info("Фоновые замеры завершены, целей с записью в БД: %s", n)
            finally:
                db.close()
        except Exception:
            log.exception("Фоновый запуск замеров")
        finally:
            with _manual_probe_lock:
                _manual_probe_running = False

    threading.Thread(target=job, name="manual-probes", daemon=True).start()
    return True


def run_target_probe(db: Session, target: MonitoredTarget) -> list[Measurement]:
    prov = target.provider
    if not prov.is_active:
        _http_access.info(
            "probe | skip target_id=%s model=%s reason=provider_inactive",
            target.id,
            target.model_name,
        )
        return []
    api_key = decrypt_secret(prov.api_key_encrypted)
    if not api_key.strip():
        log.warning("Провайдер %s без API-ключа, пропуск", prov.slug)
        _http_access.info(
            "probe | skip target_id=%s model=%s reason=no_api_key provider=%s",
            target.id,
            target.model_name,
            prov.slug,
        )
        return []

    gs = db.get(GlobalSettings, 1)
    if gs is None:
        raise RuntimeError("GlobalSettings не инициализированы")

    prompt = gs.benchmark_prompt
    warmup = target.warmup_runs if target.warmup_runs else gs.default_warmup
    timeout = gs.default_timeout

    metrics_list, batch_id = run_probe(
        prov.base_url.rstrip("/"),
        api_key,
        target.model_name,
        prompt,
        max_tokens=target.max_tokens,
        temperature=target.temperature,
        timeout=timeout,
        stream=target.use_stream,
        runs=target.runs_per_probe,
        warmup=warmup,
    )
    ok_n = sum(1 for m in metrics_list if m.success)
    _http_access.info(
        "probe | target_id=%s model=%s batch=%s provider=%s stream=%s "
        "runs=%s ok=%s base_url=%s (исходящие вызовы chat к провайдеру в этом цикле)",
        target.id,
        target.model_name,
        batch_id,
        prov.slug,
        target.use_stream,
        len(metrics_list),
        ok_n,
        prov.base_url.rstrip("/"),
    )

    rows: list[Measurement] = []
    now = datetime.now(timezone.utc)
    for idx, m in enumerate(metrics_list):
        row = Measurement(
            target_id=target.id,
            batch_id=batch_id,
            run_index=idx,
            created_at=now,
            success=m.success,
            error_message=m.error,
            http_status=m.http_status,
            ttft_s=m.ttft_s,
            total_s=m.total_s,
            prompt_tokens=m.prompt_tokens,
            completion_tokens=m.completion_tokens,
            output_chars=m.output_chars,
            gen_tps=m.gen_tps,
            e2e_tps=m.e2e_tps,
            stream=m.stream,
            chunk_count=m.chunk_count,
            usage_from_api=m.usage_from_api,
            inter_chunk_gap_mean_s=m.inter_chunk_gap_mean_s,
            inter_chunk_gap_max_s=m.inter_chunk_gap_max_s,
        )
        db.add(row)
        rows.append(row)
    db.commit()
    for r in rows:
        db.refresh(r)
    return rows


def run_all_enabled_probes(db: Session, *, probe_cycle_source: str = "scheduler") -> int:
    cap = _max_parallel_probe_workers()
    _http_access.info(
        "probes | cycle start source=%s parallel_max=%s (цели независимо, по потоку на модель)",
        probe_cycle_source,
        cap,
    )
    targets = (
        db.query(MonitoredTarget)
        .join(Provider)
        .filter(MonitoredTarget.enabled.is_(True), Provider.is_active.is_(True))
        .all()
    )
    ids: list[int] = []
    for t in targets:
        if not t.model_name.strip():
            _http_access.info("probe | skip target_id=%s reason=empty_model_name", t.id)
        else:
            ids.append(t.id)

    if not ids:
        _http_access.info(
            "probes | cycle end source=%s targets_with_saved_rows=0 candidates=%s",
            probe_cycle_source,
            len(targets),
        )
        return 0

    workers = min(cap, len(ids))
    _http_access.info(
        "probes | parallel pool targets=%s workers=%s (на цель — один поток; внутри цели warmup+runs идут по очереди)",
        len(ids),
        workers,
    )
    n = 0
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="probe") as pool:
        futures = [pool.submit(_probe_target_by_id, tid) for tid in ids]
        for fut in as_completed(futures):
            try:
                n += int(fut.result())
            except Exception:
                log.exception("Сбой future замера")
    _http_access.info(
        "probes | cycle end source=%s targets_with_saved_rows=%s candidates=%s workers=%s",
        probe_cycle_source,
        n,
        len(targets),
        workers,
    )
    return n
