"""Запуск замеров и запись в БД."""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.access_logging import access_http_logger
from app.crypto_util import decrypt_secret
from app.db import get_session_local
from app.models import GlobalSettings, Measurement, MonitoredTarget, Provider
from llm_benchmark.core import run_probe

log = logging.getLogger(__name__)
_http_access = access_http_logger()

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
    _http_access.info(
        "probes | cycle start source=%s (замеры не видны как входящий HTTP — это исходящие запросы к LLM)",
        probe_cycle_source,
    )
    targets = (
        db.query(MonitoredTarget)
        .join(Provider)
        .filter(MonitoredTarget.enabled.is_(True), Provider.is_active.is_(True))
        .all()
    )
    n = 0
    for t in targets:
        if not t.model_name.strip():
            _http_access.info("probe | skip target_id=%s reason=empty_model_name", t.id)
            continue
        try:
            rows = run_target_probe(db, t)
            if rows:
                n += 1
        except Exception:
            log.exception("Ошибка замера target_id=%s", t.id)
            _http_access.info("probe | error target_id=%s see app log", t.id)
    _http_access.info(
        "probes | cycle end source=%s targets_with_saved_rows=%s candidates=%s",
        probe_cycle_source,
        n,
        len(targets),
    )
    return n
