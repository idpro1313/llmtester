from __future__ import annotations

# GRACE[M-PAGES][HTTP][BLOCK_UIRouter]
# CONTRACT: Jinja2-страницы, setup/login, /dashboard, /dashboard/charts, admin; GET /health + version.

import logging
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.access_logging import clear_requests_log_files
from app.auth import has_any_admin, hash_password, login_user, session_admin_user
from app.crypto_util import encrypt_secret
from app.db import get_db
from app.log_reader import log_file_path, read_requests_log_tail
from app.models import AdminUser, GlobalSettings, Measurement, MonitoredTarget, Provider
from app.probe_kinds import (
    PROBE_KIND_LABELS_RU,
    normalize_probe_kind,
    probe_kind_choices,
)
from app.services.probe import run_all_enabled_probes_in_background
from app.task_config import TaskConfigError, parse_and_sanitize_task_config, task_config_json_dumps
from app.version_info import get_version

_TPL = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(_TPL))
router = APIRouter()
_log = logging.getLogger(__name__)


def _ctx(request: Request, **extra):
    return {"request": request, "app_version": get_version(), **extra}


def _tpl(request: Request, name: str, *, status_code: int = 200, **ctx: Any):
    """Starlette: TemplateResponse(request, name, context, status_code=...)."""
    return templates.TemplateResponse(request, name, _ctx(request, **ctx), status_code=status_code)


def _need_user(request: Request, db: Session) -> AdminUser | RedirectResponse:
    u = session_admin_user(request, db)
    if u is None:
        return RedirectResponse("/login", status_code=302)
    return u


@router.get("/login")
def login_page(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
):
    if request.session.get("admin_user_id"):
        return RedirectResponse("/dashboard", status_code=302)
    if not has_any_admin(db):
        return RedirectResponse("/setup", status_code=302)
    q = request.query_params.get("msg", "")
    msg = ""
    msg_ok = False
    if q == "created":
        msg = "Учётная запись создана. Войдите."
        msg_ok = True
    return _tpl(request, "login.html", msg=msg, msg_ok=msg_ok)


@router.post("/login")
def login_post(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    username: str = Form(...),
    password: str = Form(...),
):
    user = login_user(db, username.strip(), password)
    if user is None:
        return _tpl(
            request,
            "login.html",
            msg="Неверный логин или пароль",
            msg_ok=False,
            status_code=401,
        )
    request.session["admin_user_id"] = user.id
    return RedirectResponse("/dashboard", status_code=302)


@router.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=302)


@router.get("/setup")
def setup_page(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    msg: str = "",
):
    if request.session.get("admin_user_id"):
        return RedirectResponse("/dashboard", status_code=302)
    if has_any_admin(db):
        return RedirectResponse("/login", status_code=302)
    return _tpl(request, "setup.html", msg=msg)


@router.post("/setup")
def setup_post(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    username: str = Form(...),
    password: str = Form(...),
    password2: str = Form(...),
):
    if has_any_admin(db):
        return RedirectResponse("/login", status_code=302)
    u = username.strip()
    if len(u) < 2:
        return _tpl(request, "setup.html", msg="Логин не короче 2 символов.", status_code=400)
    if len(password) < 8:
        return _tpl(request, "setup.html", msg="Пароль не короче 8 символов.", status_code=400)
    if password != password2:
        return _tpl(request, "setup.html", msg="Пароли не совпадают.", status_code=400)
    try:
        db.add(AdminUser(username=u, password_hash=hash_password(password)))
        db.commit()
    except IntegrityError:
        db.rollback()
        return _tpl(request, "setup.html", msg="Такой логин уже занят.", status_code=400)
    return RedirectResponse("/login?msg=created", status_code=302)


@router.get("/")
def root(request: Request, db: Annotated[Session, Depends(get_db)]):
    if not request.session.get("admin_user_id"):
        if not has_any_admin(db):
            return RedirectResponse("/setup", status_code=302)
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
    n_raw = request.query_params.get("n")
    metrics_cleared_n: int | None = int(n_raw) if n_raw is not None and n_raw.isdigit() else None
    return _tpl(
        request,
        "dashboard.html",
        user=u,
        targets=targets,
        msg=msg,
        metrics_cleared_n=metrics_cleared_n,
    )


@router.get("/dashboard/charts")
def dashboard_charts(request: Request, db: Annotated[Session, Depends(get_db)]):
    u = _need_user(request, db)
    if isinstance(u, RedirectResponse):
        return u
    return _tpl(request, "dashboard_charts.html", user=u)


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
    return _tpl(request, "providers.html", user=u, providers=rows, msg=qmsg)


@router.get("/admin/providers/{pid}")
def admin_provider_edit(request: Request, db: Annotated[Session, Depends(get_db)], pid: int):
    u = _need_user(request, db)
    if isinstance(u, RedirectResponse):
        return u
    p = db.get(Provider, pid)
    if p is None:
        raise HTTPException(404)
    return _tpl(request, "provider_edit.html", user=u, provider=p, msg="")


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
            return _tpl(request, "provider_edit.html", user=u, provider=p, msg=str(e), status_code=400)
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
    return _tpl(
        request,
        "targets.html",
        user=u,
        targets=rows,
        msg=qmsg,
        probe_kind_labels=PROBE_KIND_LABELS_RU,
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
        probe_kind="chat",
        task_config_json="{}",
        enabled=True,
        max_tokens=512,
        temperature=0.2,
        use_stream=True,
        runs_per_probe=1,
        warmup_runs=0,
    )
    setattr(t, "_virtual_new", True)
    return _tpl(
        request,
        "target_edit.html",
        user=u,
        target=t,
        providers=providers,
        is_new=True,
        probe_kind_choices=probe_kind_choices(),
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
    return _tpl(
        request,
        "target_edit.html",
        user=u,
        target=t,
        providers=providers,
        is_new=False,
        probe_kind_choices=probe_kind_choices(),
    )


@router.post("/admin/targets/new")
def admin_target_create(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    provider_id: int = Form(...),
    model_name: str = Form(...),
    probe_kind: str = Form("chat"),
    task_config_json: str = Form("{}"),
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
    providers = db.scalars(select(Provider).order_by(Provider.sort_order)).all()
    tc_raw = (task_config_json or "").strip() or "{}"
    try:
        cfg = parse_and_sanitize_task_config(tc_raw)
    except TaskConfigError as e:
        t = MonitoredTarget(
            provider_id=provider_id,
            model_name=model_name.strip(),
            probe_kind=normalize_probe_kind(probe_kind),
            task_config_json=tc_raw,
            enabled=enabled in ("1", "on", "true", "yes"),
            max_tokens=max_tokens,
            temperature=temperature,
            use_stream=use_stream in ("1", "on", "true", "yes"),
            runs_per_probe=max(1, runs_per_probe),
            warmup_runs=max(0, warmup_runs),
        )
        setattr(t, "_virtual_new", True)
        return _tpl(
            request,
            "target_edit.html",
            user=u,
            target=t,
            providers=providers,
            is_new=True,
            probe_kind_choices=probe_kind_choices(),
            form_error=str(e),
            status_code=400,
        )
    kind = normalize_probe_kind(probe_kind)
    t = MonitoredTarget(
        provider_id=provider_id,
        model_name=model_name.strip(),
        probe_kind=kind,
        task_config_json=task_config_json_dumps(cfg),
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
    probe_kind: str = Form("chat"),
    task_config_json: str = Form("{}"),
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
    providers = db.scalars(select(Provider).order_by(Provider.sort_order)).all()
    tc_raw = (task_config_json or "").strip() or "{}"
    try:
        cfg = parse_and_sanitize_task_config(tc_raw)
    except TaskConfigError as e:
        t.provider_id = provider_id
        t.model_name = model_name.strip()
        t.probe_kind = normalize_probe_kind(probe_kind)
        t.task_config_json = tc_raw
        t.enabled = enabled in ("1", "on", "true", "yes")
        t.max_tokens = max_tokens
        t.temperature = temperature
        t.use_stream = use_stream in ("1", "on", "true", "yes")
        t.runs_per_probe = max(1, runs_per_probe)
        t.warmup_runs = max(0, warmup_runs)
        return _tpl(
            request,
            "target_edit.html",
            user=u,
            target=t,
            providers=providers,
            is_new=False,
            probe_kind_choices=probe_kind_choices(),
            form_error=str(e),
            status_code=400,
        )
    t.provider_id = provider_id
    t.model_name = model_name.strip()
    t.probe_kind = normalize_probe_kind(probe_kind)
    t.task_config_json = task_config_json_dumps(cfg)
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
    return _tpl(request, "settings.html", user=u, settings=gs, msg=qmsg)


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


@router.get("/admin/logs")
def admin_logs(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    lines: int = Query(500, ge=50, le=3000),
):
    u = _need_user(request, db)
    if isinstance(u, RedirectResponse):
        return u
    text, files = read_requests_log_tail(lines)
    path = log_file_path()
    flash = request.query_params.get("msg", "")
    if not text.strip():
        if path.is_file() and path.stat().st_size == 0:
            text = "(файл пуст)"
        elif not path.is_file():
            text = "(файл requests.log ещё не создан — сделайте запросы к приложению или дождитесь старта)"
        else:
            text = "(нет строк в выбранном диапазоне)"
    return _tpl(
        request,
        "logs.html",
        user=u,
        log_text=text,
        log_files=files,
        lines=lines,
        log_path=str(path.resolve()),
        log_flash=flash,
    )


@router.post("/admin/logs/clear")
def admin_logs_clear(request: Request, db: Annotated[Session, Depends(get_db)]):
    u = _need_user(request, db)
    if isinstance(u, RedirectResponse):
        return u
    err = clear_requests_log_files()
    if err:
        return RedirectResponse("/admin/logs?msg=clear_err", status_code=302)
    return RedirectResponse("/admin/logs?msg=cleared", status_code=302)


@router.post("/admin/measurements/clear")
def admin_measurements_clear(request: Request, db: Annotated[Session, Depends(get_db)]):
    u = _need_user(request, db)
    if isinstance(u, RedirectResponse):
        return u
    try:
        r = db.execute(delete(Measurement))
        db.commit()
        rc = r.rowcount
        if rc is not None and rc >= 0:
            return RedirectResponse(f"/dashboard?msg=metrics_cleared&n={rc}", status_code=302)
        return RedirectResponse("/dashboard?msg=metrics_cleared", status_code=302)
    except Exception:
        db.rollback()
        _log.exception("Очистка таблицы measurements")
        return RedirectResponse("/dashboard?msg=metrics_clear_err", status_code=302)


@router.post("/admin/run-now")
def admin_run_now(request: Request, db: Annotated[Session, Depends(get_db)]):
    u = _need_user(request, db)
    if isinstance(u, RedirectResponse):
        return u
    if not run_all_enabled_probes_in_background():
        return RedirectResponse("/dashboard?msg=run_busy", status_code=302)
    return RedirectResponse("/dashboard?msg=run_bg", status_code=302)


@router.get("/health")
def health():
    return {"status": "ok", "version": get_version()}
