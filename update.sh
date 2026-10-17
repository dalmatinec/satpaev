#!/usr/bin/env bash
# Обновление: подтянуть код из GitHub и перезапустить. Данные и бэкапы не трогаются.
set -euo pipefail
cd "$(dirname "$0")"
git pull --ff-only
docker compose up -d --build
docker image prune -f >/dev/null
docker compose ps
