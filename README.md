# LLM Inference Monitor

Сервис для **сравнения производительности инференса** нескольких LLM по **OpenAI-compatible API** у провайдеров (в т.ч. **Cloud.ru**, **Yandex Cloud**, **MWS**): периодические замеры, хранение в **PostgreSQL** (или SQLite локально), **веб-админка** и **дашборд**.

## Возможности

- Учётные данные провайдеров: base URL + API-ключ (ключи **шифруются** в БД через Fernet, нужен `FERNET_KEY`).
- Список **целей мониторинга**: провайдер, имя модели, `max_tokens`, температура, стриминг, число замеров за цикл, прогрев.
- **Интервал** автозамеров (не меньше 30 с), общий промпт, таймаут HTTP, прогрев по умолчанию.
- **Метрики в БД**: TTFT, полное время, токены (и признак `usage_from_api`), e2e/gen tok/s, число чанков, средний и макс. интервал между чанками, HTTP-статус, текст ошибки, успех/неуспех.
- **Дашборд**: графики по времени и **сводка** с p50/p95/p99 по успешным замерам и долей ошибок.
- **CLI** `benchmark.py` — прежний сценарий замера в файл/консоль (логика в пакете `llm_benchmark`).

## Быстрый старт (Docker)

1. Скопируйте `.env.example` в `.env`.
2. Сгенерируйте ключ Fernet и вставьте в `.env`:

   ```bash
   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
   ```

3. Задайте `SESSION_SECRET`, смените `ADMIN_PASSWORD`.

   ```bash
   docker compose up --build
   ```

4. Откройте http://localhost:8000 — вход: `ADMIN_USERNAME` / `ADMIN_PASSWORD`.

5. В разделе **Провайдеры** укажите реальные **base URL** из документации API (OpenAI-compatible), вставьте ключ, включите провайдера.

6. В **Модели** добавьте цели (идентификатор модели как у провайдера).

7. В **Настройки** при необходимости измените интервал и текст промпта.

> URL в шаблонах провайдеров — **заглушки**; замените на значения из документации Cloud.ru / Yandex / MWS.

## Локальный запуск (SQLite)

```bash
pip install -r requirements.txt
set PYTHONPATH=.
set FERNET_KEY=...   # обязательно
set DATABASE_URL=sqlite:///./data/monitor.db
mkdir data
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

## CLI-бенчмарк (без веба)

```bash
set PYTHONPATH=.
python benchmark.py --model YOUR_MODEL --base-url https://.../v1 --api-key ...
```

Отчёты по умолчанию в каталоге `workspace/` (создайте при необходимости).

## API для графиков (с сессией админа)

- `GET /api/metrics/series?hours=24&target_id=` — точки для графиков.
- `GET /api/metrics/summary?hours=24` — агрегаты по целям (перцентили).
- `GET /api/targets/options` — список целей для фильтра.

## Структура проекта

- `llm_benchmark/` — ядро замеров (стриминг, метрики, `run_probe`).
- `app/` — FastAPI, шаблоны, планировщик APScheduler.
- `benchmark.py` — CLI-обёртка.

## Отправка проекта в GitLab

Git-сервер: **`https://gitlabacr.aplanadc.ru/`**, группа/namespace: **`IYatsishen`**.

1. В веб-интерфейсе создайте **пустой проект** (без README) в `IYatsishen`, задайте имя, например `llmtester`.
2. Скопируйте HTTPS-URL из **Code → Clone** — он будет вида  
   `https://gitlabacr.aplanadc.ru/IYatsishen/<имя-проекта>.git`
3. Локально:

   ```bash
   git remote remove origin   # если origin уже указывал куда-то ещё
   git remote add origin https://gitlabacr.aplanadc.ru/IYatsishen/<имя-проекта>.git
   git branch -M main
   git push -u origin main
   ```

Для **HTTPS** GitLab обычно нужен **Personal Access Token** вместо пароля при запросе учётных данных.

CI/CD в репозитории **не используется** (файла `.gitlab-ci.yml` нет).

## Безопасность

Смените пароль администратора и `SESSION_SECRET` в продакшене. Не коммитьте `.env` с реальными ключами.
