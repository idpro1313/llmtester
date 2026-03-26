from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth import require_admin
from app.crypto_util import decrypt_secret
from app.db import get_db
from app.models import AdminUser, Provider
from app.services.openai_models import list_model_ids, models_endpoint_url

router = APIRouter(tags=["api"])


@router.get("/providers/{provider_id}/models")
def provider_models_list(
    provider_id: int,
    db: Annotated[Session, Depends(get_db)],
    _user: Annotated[AdminUser, Depends(require_admin)],
) -> dict[str, Any]:
    """Список моделей у провайдера (OpenAI-compatible /v1/models)."""
    prov = db.get(Provider, provider_id)
    if prov is None:
        raise HTTPException(status_code=404, detail="Провайдер не найден")

    api_key = decrypt_secret(prov.api_key_encrypted)
    if not api_key.strip():
        return {
            "ok": False,
            "error": "no_api_key",
            "message": "У провайдера не задан API-ключ. Сохраните ключ в разделе «Провайдеры».",
            "models": [],
        }

    upstream_url = models_endpoint_url(prov.base_url)
    ids, err = list_model_ids(prov.base_url, api_key)
    if err is not None:
        return {
            "ok": False,
            "error": "upstream",
            "message": err,
            "upstream_url": upstream_url,
            "provider_base_url": prov.base_url,
            "models": [],
        }

    return {"ok": True, "models": [{"id": i} for i in ids]}
