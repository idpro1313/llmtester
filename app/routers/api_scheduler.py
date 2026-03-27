from __future__ import annotations

# GRACE[M-API-SCHEDULER][HTTP][BLOCK_SchedulerAPI]
# CONTRACT: status, start, stop планировщика замеров; require_admin.

from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth import require_admin
from app.db import get_db
from app.models import AdminUser
from app.scheduler import (
    pause_scheduled_probes,
    resume_scheduled_probes,
    scheduler_status_dict,
)

router = APIRouter(tags=["api"])


@router.get("/scheduler/status")
def scheduler_status(
    db: Annotated[Session, Depends(get_db)],
    _user: Annotated[AdminUser, Depends(require_admin)],
) -> dict[str, Any]:
    return scheduler_status_dict(db)


@router.post("/scheduler/start")
def scheduler_start(
    db: Annotated[Session, Depends(get_db)],
    _user: Annotated[AdminUser, Depends(require_admin)],
) -> dict[str, Any]:
    resume_scheduled_probes()
    return scheduler_status_dict(db)


@router.post("/scheduler/stop")
def scheduler_stop(
    db: Annotated[Session, Depends(get_db)],
    _user: Annotated[AdminUser, Depends(require_admin)],
) -> dict[str, Any]:
    pause_scheduled_probes()
    return scheduler_status_dict(db)
