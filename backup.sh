#!/usr/bin/env bash
# Ручной бэкап базы в папку backups (автоматический бот делает сам каждый день).
set -euo pipefail
cd "$(dirname "$0")"
set -a; . ./.env; set +a
mkdir -p backups
FILE="backups/manual_$(date +%Y%m%d_%H%M%S).dump"
docker compose exec -T db pg_dump -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -Fc -Z 6 > "${FILE}"
echo "✅ ${FILE} ($(du -h "${FILE}" | cut -f1))"
