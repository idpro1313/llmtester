# LLM Inference Monitor

**Версия:** см. файл [`VERSION`](VERSION) в корне репозитория (`GET /health` возвращает поле `version`).

Сервис для **сравнения производительности инференса** нескольких LLM по **OpenAI-compatible API** у провайдеров (в т.ч. **Cloud.ru**, **Yandex Cloud**, **MWS**): периодические замеры, хранение в **SQLite** (**`docker compose`**: файл **`./data/monitor.db`** на машине, каталог смонтирован в контейнер), **веб-админка** и **дашборд**.

## Возможности

- Учётные данные провайдеров: base URL + API-ключ (ключи **шифруются** в БД; секрет Fernet при первом запуске **генерируется и хранится в БД**, опционально через переменную `FERNET_KEY`).
- **Первый вход**: логин и пароль администратора задаются **один раз** на странице настройки (файл `.env` не нужен).
- Список **целей мониторинга**: провайдер, имя модели, `max_tokens`, температура, стриминг, число замеров за цикл, прогрев.
- **Интервал** автоматических замеров (не меньше 30 с), общий промпт, таймаут HTTP, прогрев по умолчанию.
- **Метрики в БД**: TTFT, полное время, токены (и признак `usage_from_api`), e2e/gen tok/s, число чанков, средний и макс. интервал между чанками, HTTP-статус, текст ошибки, успех/неуспех.
- **Дашборд**: графики по времени и **сводка** с p50/p95/p99 по успешным замерам и долей ошибок.
- **CLI** `benchmark.py` — прежний сценарий замера в файл/консоль (логика в пакете `llm_benchmark`).

## Быстрый старт (Docker)

Файл **`.env` не используется**. В каталоге `./data` на хосте хранятся **`monitor.db`**, **`.session_secret`** (подпись cookie) и при необходимости сгенерированный ключ Fernet в БД.

1. Запуск из каталога с `docker-compose.yml`. Имя Compose-проекта, сервиса и контейнера — **`llmtester`**, чтобы не пересекаться с другими стеками.

   ```bash
   docker compose up --build
   ```

   На Linux/macOS/Git Bash можно обновлять и поднимать сервис одной командой (исполняемый скрипт в репозитории):

   ```bash
   ./docker-up.sh
   ```

2. Откройте http://localhost:4444 (порт см. в `docker-compose.yml`).

3. При **первом** открытии откроется **первичная настройка** — задайте логин и пароль администратора, затем войдите.

4. В **Провайдеры** укажите base URL и API-ключ (OpenAI-compatible), включите провайдера.

5. В **Модели** добавьте цели, в **Настройки** при необходимости измените интервал и промпт.

> URL в шаблонах провайдеров — **заглушки**; замените на значения из документации Cloud.ru / Yandex / MWS.

## Локальный запуск (SQLite)

```bash
pip install -r requirements.txt
set PYTHONPATH=.
set DATABASE_URL=sqlite:///./data/monitor.db
set MONITOR_DATA_DIR=data
mkdir data
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Первый визит: **http://127.0.0.1:8000/setup**.

## Переменные окружения (опционально)

Без файла `.env`, только при необходимости: `DATABASE_URL`, `MONITOR_DATA_DIR`, `SESSION_SECRET`, `FERNET_KEY`.

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

Каталог **`data/`** содержит БД, подпись сессий и зашифрованные ключи API — ограничьте доступ и делайте резервные копии. Не коммитьте `data/` в Git.
