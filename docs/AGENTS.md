# AGENTS — карта проекта LLM Inference Monitor

Семантическая карта для агентов и людей: стек, модули GRACE (M-*), публичные маршруты и соглашения. Детальные контракты модулей — в `docs/development-plan.xml`; трассы проверок — в `docs/verification-plan.xml`; граф файлов — в `docs/knowledge-graph.xml`.

## Обзор

- **Назначение:** мониторинг производительности инференса LLM по OpenAI-compatible API (несколько провайдеров, цели с параметрами, периодические замеры, SQLite, веб-админка и дашборд).
- **Стек:** Python, FastAPI, SQLAlchemy 2, Jinja2, APScheduler, OpenAI SDK, openpyxl. См. `docs/technology.xml`.
- **Версия:** файл `VERSION` в корне; `GET /health` отдаёт поле `version` (см. `app/version_info.py`).

## Структура директорий

| Путь | Роль |
|------|------|
| `app/main.py` | Точка входа ASGI, сборка приложения (**M-APP**). |
| `app/routers/pages.py` | HTML UI, `/health` (**M-PAGES**). |
| `app/routers/api_*.py` | JSON API под префиксом `/api` (**M-API-***). |
| `app/services/` | Бизнес-логика замеров, экспорт, список моделей upstream. |
| `app/models.py`, `app/db.py` | ORM и сессии (**M-DATA**, **M-DB**). |
| `app/scheduler.py` | APScheduler (**M-SCHEDULER**). |
| `llm_benchmark/` | Ядро замеров: **M-LLM-BENCHMARK** (`core.py`, чат), **M-LLM-BENCHMARK-EXTRA** (`non_chat_probes.py`); `benchmark.py` — CLI (чат). |
| `app/probe_kinds.py`, `app/task_config.py` | Константы типов замеров и парсинг `task_config_json`. |
| `app/schema_migrate.py` | Additive колонки БД (**M-SCHEMA-MIGRATE**). |
| `docs/` | GRACE: `requirements.xml`, `technology.xml`, `development-plan.xml`, `verification-plan.xml`, `knowledge-graph.xml`, этот файл. |

## API (кратко)

Публичные HTML-маршруты определены в `app/routers/pages.py` (login, setup, `/dashboard` — сводка и ошибки, `/dashboard/charts` — крупные графики Chart.js, admin-разделы).

Под `/api` (см. `app/main.py` — префикс задаётся при подключении роутеров):

| Метод | Путь | Назначение |
|-------|------|------------|
| GET | `/api/metrics/series` | Ряды для графиков |
| GET | `/api/metrics/summary` | Сводка, перцентили |
| GET | `/api/metrics/export` | Скачивание Excel |
| GET | `/api/targets/options` | Опции фильтра целей |
| GET | `/api/providers/{id}/models` | Список моделей у провайдера |
| GET | `/api/scheduler/status` | Статус планировщика |
| POST | `/api/scheduler/start` | Возобновить автозамеры |
| POST | `/api/scheduler/stop` | Пауза автозамеров |

Большинство эндпоинтов `/api/*` требуют сессии администратора (`require_admin`).

## GRACE

- **Идентификаторы модулей M-*** согласованы с `docs/development-plan.xml`.
- В Python в начале ключевых модулей: `# GRACE[M-*][...][BLOCK_*]` и при необходимости `# CONTRACT: ...` (формат в `docs/technology.xml`).
- После изменений границ модулей, маршрутов или контрактов API обновляйте XML в `docs/` и этот файл согласованно.

## История итераций

Файл `docs/HISTORY.md` ведётся локально и **не коммитится** (см. `.gitignore`).
