"""Запуск замеров и запись в БД."""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.crypto_util import decrypt_secret
from app.db import get_session_local
from app.models import GlobalSettings, Measurement, MonitoredTarget, Provider
from llm_benchmark.core import run_probe

log = logging.getLogger(__name__)

_manual_probe_lock = threading.Lock()
_manual_probe_running = False


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
                n = run_all_enabled_probes(db)
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
        return []
    api_key = decrypt_secret(prov.api_key_encrypted)
    if not api_key.strip():
        log.warning("Провайдер %s без API-ключа, пропуск", prov.slug)
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


def run_all_enabled_probes(db: Session) -> int:
    targets = (
        db.query(MonitoredTarget)
        .join(Provider)
        .filter(MonitoredTarget.enabled.is_(True), Provider.is_active.is_(True))
        .all()
    )
    n = 0
    for t in targets:
        if not t.model_name.strip():
            continue
        try:
            rows = run_target_probe(db, t)
            if rows:
                n += 1
        except Exception:
            log.exception("Ошибка замера target_id=%s", t.id)
    return n
