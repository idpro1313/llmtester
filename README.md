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

## Публикация образа в GitLab Container Registry (`gitlabacr.aplanadc.ru`)

В репозитории есть [`.gitlab-ci.yml`](.gitlab-ci.yml): при пуше в **основную ветку** (`main`/`master` — совпадает с **Default branch** в настройках проекта) или при пуше **git-тега** Kaniko собирает образ и пушит в реестр вашего GitLab.

1. Создайте проект в GitLab под путём вроде `IYatsishen/<имя-проекта>` (хост Git — обычно отдельный от `gitlabacr`, например корпоративный GitLab).
2. Убедитесь, что в проекте включён **Container Registry**.
3. Привяжите remote и отправьте код:

   ```bash
   git remote add origin https://<ваш-gitlab>/IYatsishen/<имя-проекта>.git
   git add .
   git commit -m "Initial commit: LLM inference monitor"
   git push -u origin main
   ```

4. После успешного pipeline образ будет доступен по адресу, который GitLab показывает в **Deploy → Container Registry**, например:

   `gitlabacr.aplanadc.ru/iyatsishen/<имя-проекта>:latest`

   (регистр пути часто **в нижнем регистре** — смотрите точное имя в UI).

**Ручная публикация** (с машины с Docker), если CI не используете:

```bash
docker login gitlabacr.aplanadc.ru -u <логин> -p <personal_access_token_или_deploy_token>
docker build -t gitlabacr.aplanadc.ru/iyatsishen/<имя-проекта>:latest .
docker push gitlabacr.aplanadc.ru/iyatsishen/<имя-проекта>:latest
```

Токен нужен с правом `write_registry` (или deploy token с `write_package_registry`).

## Безопасность

Смените пароль администратора и `SESSION_SECRET` в продакшене. Не коммитьте `.env` с реальными ключами.
