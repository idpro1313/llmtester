from __future__ import annotations

import statistics
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.auth import require_admin
from app.db import get_db
from app.models import AdminUser, Measurement, MonitoredTarget, Provider

router = APIRouter(tags=["api"])


def _percentile(sorted_vals: list[float], p: float) -> float | None:
    if not sorted_vals:
        return None
    k = (len(sorted_vals) - 1) * p / 100.0
    f = int(k)
    c = min(f + 1, len(sorted_vals) - 1)
    if f == c:
        return sorted_vals[f]
    return sorted_vals[f] + (sorted_vals[c] - sorted_vals[f]) * (k - f)


@router.get("/metrics/series")
def metrics_series(
    db: Annotated[Session, Depends(get_db)],
    _user: Annotated[AdminUser, Depends(require_admin)],
    hours: int = Query(24, ge=1, le=168),
    target_id: int | None = None,
) -> dict[str, Any]:
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    q = (
        select(Measurement)
        .where(Measurement.created_at >= since)
        .options(joinedload(Measurement.target).joinedload(MonitoredTarget.provider))
        .order_by(Measurement.created_at)
    )
    if target_id is not None:
        q = q.where(Measurement.target_id == target_id)
    rows = db.scalars(q).unique().all()
    points = []
    for m in rows:
        t = m.target
        p = t.provider
        label = f"{p.display_name} / {t.model_name}"
        points.append(
            {
                "t": m.created_at.isoformat(),
                "measurement_id": m.id,
                "target_id": t.id,
                "batch_id": m.batch_id,
                "run_index": m.run_index,
                "label": label,
                "provider_slug": p.slug,
                "success": m.success,
                "error_message": m.error_message,
                "http_status": m.http_status,
                "ttft_s": m.ttft_s,
                "total_s": m.total_s,
                "prompt_tokens": m.prompt_tokens,
                "completion_tokens": m.completion_tokens,
                "output_chars": m.output_chars,
                "gen_tps": m.gen_tps,
                "e2e_tps": m.e2e_tps,
                "stream": m.stream,
                "chunk_count": m.chunk_count,
                "usage_from_api": m.usage_from_api,
                "inter_chunk_gap_mean_s": m.inter_chunk_gap_mean_s,
                "inter_chunk_gap_max_s": m.inter_chunk_gap_max_s,
            }
        )
    return {"points": points}


@router.get("/metrics/summary")
def metrics_summary(
    db: Annotated[Session, Depends(get_db)],
    _user: Annotated[AdminUser, Depends(require_admin)],
    hours: int = Query(24, ge=1, le=168),
    target_id: int | None = None,
) -> dict[str, Any]:
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    q = (
        select(Measurement)
        .where(Measurement.created_at >= since)
        .options(joinedload(Measurement.target).joinedload(MonitoredTarget.provider))
    )
    if target_id is not None:
        q = q.where(Measurement.target_id == target_id)
    rows = db.scalars(q).unique().all()
    by_target: dict[int, list[Measurement]] = {}
    for m in rows:
        by_target.setdefault(m.target_id, []).append(m)

    summaries = []
    for tid, ms in by_target.items():
        t = ms[0].target
        p = t.provider
        ok = [m for m in ms if m.success]

        def pull(attr: str) -> list[float]:
            return [float(getattr(m, attr)) for m in ok if getattr(m, attr) is not None]

        ttft = sorted(pull("ttft_s"))
        tot = sorted(pull("total_s"))
        e2e = sorted(pull("e2e_tps"))
        gen = sorted(pull("gen_tps"))
        ptok = sorted(pull("prompt_tokens"))
        ctok = sorted(pull("completion_tokens"))
        och = sorted(pull("output_chars"))
        chn = sorted(pull("chunk_count"))
        gapm = sorted(pull("inter_chunk_gap_mean_s"))
        gapx = sorted(pull("inter_chunk_gap_max_s"))

        def pack(vals: list[float]) -> dict[str, float | None]:
            if not vals:
                return {"mean": None, "p50": None, "p95": None, "p99": None, "min": None, "max": None}
            return {
                "mean": statistics.mean(vals),
                "p50": _percentile(vals, 50),
                "p95": _percentile(vals, 95),
                "p99": _percentile(vals, 99),
                "min": vals[0],
                "max": vals[-1],
            }

        with_ct = [m for m in ok if m.completion_tokens is not None]
        usage_api_share = (
            (sum(1 for m in with_ct if m.usage_from_api) / len(with_ct)) if with_ct else None
        )
        stream_share = (sum(1 for m in ok if m.stream) / len(ok)) if ok else None

        summaries.append(
            {
                "target_id": tid,
                "label": f"{p.display_name} / {t.model_name}",
                "provider_slug": p.slug,
                "samples": len(ms),
                "success_count": len(ok),
                "error_rate": (len(ms) - len(ok)) / len(ms) if ms else 0.0,
                "ttft_s": pack(ttft),
                "total_s": pack(tot),
                "e2e_tps": pack(e2e),
                "gen_tps": pack(gen),
                "prompt_tokens": pack(ptok),
                "completion_tokens": pack(ctok),
                "output_chars": pack(och),
                "chunk_count": pack(chn),
                "inter_chunk_gap_mean_s": pack(gapm),
                "inter_chunk_gap_max_s": pack(gapx),
                "stream_share": stream_share,
                "usage_api_share": usage_api_share,
            }
        )

    summaries.sort(key=lambda x: (x["provider_slug"], x["label"]))
    return {"since": since.isoformat(), "targets": summaries}


@router.get("/targets/options")
def targets_options(
    db: Annotated[Session, Depends(get_db)],
    _user: Annotated[AdminUser, Depends(require_admin)],
) -> dict[str, Any]:
    rows = db.scalars(
        select(MonitoredTarget)
        .join(MonitoredTarget.provider)
        .options(joinedload(MonitoredTarget.provider))
        .order_by(Provider.sort_order, MonitoredTarget.id)
    ).unique().all()
    return {
        "targets": [
            {
                "id": t.id,
                "label": f"{t.provider.display_name} — {t.model_name}",
            }
            for t in rows
        ]
    }
