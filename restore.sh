#!/usr/bin/env bash
# Восстановление базы из бэкапа.
#   ./restore.sh                       последний файл из папки backups
#   ./restore.sh backups/backup_X.dump конкретный файл
set -euo pipefail
cd "$(dirname "$0")"

FILE="${1:-$(ls -t backups/*.dump 2>/dev/null | head -1 || true)}"
if [ -z "${FILE}" ] || [ ! -f "${FILE}" ]; then
  echo "Файл бэкапа не найден. Положите .dump в папку backups или укажите путь." >&2
  exit 1
fi

set -a; . ./.env; set +a
echo "Восстанавливаю из ${FILE}"

docker compose up -d db
until docker compose exec -T db pg_isready -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" >/dev/null 2>&1; do sleep 1; done

docker compose stop bot poster || true
docker compose exec -T db pg_restore -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" \
  --clean --if-exists --no-owner --no-privileges < "${FILE}"
docker compose up -d bot poster

echo "✅ База восстановлена, бот перезапущен."
