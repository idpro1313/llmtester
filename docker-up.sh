#!/usr/bin/env bash
# Сборка образа и запуск/обновление контейнера (docker compose).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

echo "==> Сборка (docker compose build --pull)"
docker compose build --pull

echo "==> Запуск в фоне (docker compose up -d)"
docker compose up -d --remove-orphans

echo "==> Статус сервисов"
docker compose ps

echo "==> Готово. HTTP: порт см. в docker-compose.yml (сейчас 4444 -> 8000 в контейнере)."
