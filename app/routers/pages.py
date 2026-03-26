from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.auth import login_user, session_admin_user
from app.crypto_util import encrypt_secret
from app.db import get_db
from app.models import AdminUser, GlobalSettings, MonitoredTarget, Provider
from app.services.probe import run_all_enabled_probes

_TPL = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(_TPL))
router = APIRouter()


def _ctx(request: Request, **extra):
    return {"request": request, **extra}


def _need_user(request: Request, db: Session) -> AdminUser | RedirectResponse:
    u = session_admin_user(request, db)
    if u is None:
        return RedirectResponse("/login", status_code=302)
    return u


@router.get("/login")
def login_page(request: Request, msg: str = ""):
    if request.session.get("admin_user_id"):
        return RedirectResponse("/dashboard", status_code=302)
    return templates.TemplateResponse("login.html", _ctx(request, msg=msg))


@router.post("/login")
def login_post(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    username: str = Form(...),
    password: str = Form(...),
):
    user = login_user(db, username.strip(), password)
    if user is None:
        return templates.TemplateResponse(
            "login.html",
            _ctx(request, msg="Неверный логин или пароль"),
            status_code=401,
        )
    request.session["admin_user_id"] = user.id
    return RedirectResponse("/dashboard", status_code=302)


@router.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=302)


@router.get("/")
def root(request: Request):
    if not request.session.get("admin_user_id"):
        return RedirectResponse("/login", status_code=302)
    return RedirectResponse("/dashboard", status_code=302)


@router.get("/dashboard")
def dashboard(request: Request, db: Annotated[Session, Depends(get_db)]):
    u = _need_user(request, db)
    if isinstance(u, RedirectResponse):
        return u
    targets = db.scalars(
        select(MonitoredTarget)
        .join(MonitoredTarget.provider)
        .options(joinedload(MonitoredTarget.provider))
        .order_by(Provider.sort_order, MonitoredTarget.id)
    ).unique().all()
    msg = request.query_params.get("msg", "")
    n = request.query_params.get("n", "")
    return templates.TemplateResponse(
        "dashboard.html",
        _ctx(request, user=u, targets=targets, msg=msg, run_n=n),
    )


@router.get("/admin/providers")
def admin_providers(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    msg: str = "",
):
    u = _need_user(request, db)
    if isinstance(u, RedirectResponse):
        return u
    rows = db.scalars(select(Provider).order_by(Provider.sort_order, Provider.id)).all()
    qmsg = request.query_params.get("msg", msg)
    return templates.TemplateResponse(
        "providers.html",
        _ctx(request, user=u, providers=rows, msg=qmsg),
    )


@router.get("/admin/providers/{pid}")
def admin_provider_edit(request: Request, db: Annotated[Session, Depends(get_db)], pid: int):
    u = _need_user(request, db)
    if isinstance(u, RedirectResponse):
        return u
    p = db.get(Provider, pid)
    if p is None:
        raise HTTPException(404)
    return templates.TemplateResponse(
        "provider_edit.html",
        _ctx(request, user=u, provider=p, msg=""),
    )


@router.post("/admin/providers/{pid}")
def admin_provider_save(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    pid: int,
    display_name: str = Form(...),
    base_url: str = Form(...),
    api_key: str = Form(""),
    is_active: str = Form("0"),
):
    u = _need_user(request, db)
    if isinstance(u, RedirectResponse):
        return u
    p = db.get(Provider, pid)
    if p is None:
        raise HTTPException(404)
    p.display_name = display_name.strip()
    p.base_url = base_url.strip().rstrip("/")
    p.is_active = is_active in ("1", "on", "true", "yes")
    key = api_key.strip()
    if key:
        try:
            p.api_key_encrypted = encrypt_secret(key)
        except RuntimeError as e:
            return templates.TemplateResponse(
                "provider_edit.html",
                _ctx(request, user=u, provider=p, msg=str(e)),
                status_code=400,
            )
    db.commit()
    return RedirectResponse("/admin/providers?msg=saved", status_code=302)


@router.get("/admin/targets")
def admin_targets(request: Request, db: Annotated[Session, Depends(get_db)]):
    u = _need_user(request, db)
    if isinstance(u, RedirectResponse):
        return u
    rows = db.scalars(
        select(MonitoredTarget)
        .join(MonitoredTarget.provider)
        .options(joinedload(MonitoredTarget.provider))
        .order_by(Provider.sort_order, MonitoredTarget.id)
    ).unique().all()
    qmsg = request.query_params.get("msg", "")
    return templates.TemplateResponse(
        "targets.html",
        _ctx(request, user=u, targets=rows, msg=qmsg),
    )


@router.get("/admin/targets/new")
def admin_target_new(request: Request, db: Annotated[Session, Depends(get_db)]):
    u = _need_user(request, db)
    if isinstance(u, RedirectResponse):
        return u
    providers = db.scalars(select(Provider).order_by(Provider.sort_order)).all()
    if not providers:
        return RedirectResponse("/admin/providers?msg=add_provider_first", status_code=302)
    t = MonitoredTarget(
        provider_id=providers[0].id,
        model_name="",
        enabled=True,
        max_tokens=512,
        temperature=0.2,
        use_stream=True,
        runs_per_probe=1,
        warmup_runs=0,
    )
    setattr(t, "_virtual_new", True)
    return templates.TemplateResponse(
        "target_edit.html",
        _ctx(request, user=u, target=t, providers=providers, is_new=True),
    )


@router.get("/admin/targets/{tid}")
def admin_target_edit(request: Request, db: Annotated[Session, Depends(get_db)], tid: int):
    u = _need_user(request, db)
    if isinstance(u, RedirectResponse):
        return u
    t = db.get(MonitoredTarget, tid)
    if t is None:
        raise HTTPException(404)
    providers = db.scalars(select(Provider).order_by(Provider.sort_order)).all()
    return templates.TemplateResponse(
        "target_edit.html",
        _ctx(request, user=u, target=t, providers=providers, is_new=False),
    )


@router.post("/admin/targets/new")
def admin_target_create(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    provider_id: int = Form(...),
    model_name: str = Form(...),
    enabled: str = Form("0"),
    max_tokens: int = Form(512),
    temperature: float = Form(0.2),
    use_stream: str = Form("1"),
    runs_per_probe: int = Form(1),
    warmup_runs: int = Form(0),
):
    u = _need_user(request, db)
    if isinstance(u, RedirectResponse):
        return u
    t = MonitoredTarget(
        provider_id=provider_id,
        model_name=model_name.strip(),
        enabled=enabled in ("1", "on", "true", "yes"),
        max_tokens=max_tokens,
        temperature=temperature,
        use_stream=use_stream in ("1", "on", "true", "yes"),
        runs_per_probe=max(1, runs_per_probe),
        warmup_runs=max(0, warmup_runs),
    )
    db.add(t)
    db.commit()
    return RedirectResponse("/admin/targets?msg=created", status_code=302)


@router.post("/admin/targets/{tid}")
def admin_target_save(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    tid: int,
    provider_id: int = Form(...),
    model_name: str = Form(...),
    enabled: str = Form("0"),
    max_tokens: int = Form(512),
    temperature: float = Form(0.2),
    use_stream: str = Form("1"),
    runs_per_probe: int = Form(1),
    warmup_runs: int = Form(0),
):
    u = _need_user(request, db)
    if isinstance(u, RedirectResponse):
        return u
    t = db.get(MonitoredTarget, tid)
    if t is None:
        raise HTTPException(404)
    t.provider_id = provider_id
    t.model_name = model_name.strip()
    t.enabled = enabled in ("1", "on", "true", "yes")
    t.max_tokens = max_tokens
    t.temperature = temperature
    t.use_stream = use_stream in ("1", "on", "true", "yes")
    t.runs_per_probe = max(1, runs_per_probe)
    t.warmup_runs = max(0, warmup_runs)
    db.commit()
    return RedirectResponse("/admin/targets?msg=saved", status_code=302)


@router.post("/admin/targets/{tid}/delete")
def admin_target_delete(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    tid: int,
):
    u = _need_user(request, db)
    if isinstance(u, RedirectResponse):
        return u
    t = db.get(MonitoredTarget, tid)
    if t:
        db.delete(t)
        db.commit()
    return RedirectResponse("/admin/targets?msg=deleted", status_code=302)


@router.get("/admin/settings")
def admin_settings(request: Request, db: Annotated[Session, Depends(get_db)]):
    u = _need_user(request, db)
    if isinstance(u, RedirectResponse):
        return u
    gs = db.get(GlobalSettings, 1)
    qmsg = request.query_params.get("msg", "")
    return templates.TemplateResponse(
        "settings.html",
        _ctx(request, user=u, settings=gs, msg=qmsg),
    )


@router.post("/admin/settings")
def admin_settings_save(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    benchmark_prompt: str = Form(...),
    probe_interval_seconds: int = Form(300),
    default_warmup: int = Form(0),
    default_timeout: float = Form(120.0),
):
    u = _need_user(request, db)
    if isinstance(u, RedirectResponse):
        return u
    gs = db.get(GlobalSettings, 1)
    if gs is None:
        raise HTTPException(500, detail="Нет настроек")
    gs.benchmark_prompt = benchmark_prompt
    gs.probe_interval_seconds = max(30, probe_interval_seconds)
    gs.default_warmup = max(0, default_warmup)
    gs.default_timeout = max(5.0, default_timeout)
    db.commit()
    from app.scheduler import reschedule_from_db

    reschedule_from_db()
    return RedirectResponse("/admin/settings?msg=saved", status_code=302)


@router.post("/admin/run-now")
def admin_run_now(request: Request, db: Annotated[Session, Depends(get_db)]):
    u = _need_user(request, db)
    if isinstance(u, RedirectResponse):
        return u
    n = run_all_enabled_probes(db)
    return RedirectResponse(f"/dashboard?msg=run&n={n}", status_code=302)


@router.get("/health")
def health():
    return {"status": "ok"}
