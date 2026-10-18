#!/usr/bin/env bash
# Запуск сайта: ./deploy.sh   (повторный запуск обновляет сайт)
#   ./deploy.sh config   поменять бота, менеджера и канал
set -euo pipefail
cd "$(dirname "$0")"

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker не найден, устанавливаю..."
  curl -fsSL https://get.docker.com | sh
fi

if [ ! -f .env ]; then
  cp .env.example .env
  read -rp "Домен сайта (Enter, если пока нет): " DOMAIN
  if [ -n "${DOMAIN}" ]; then sed -i "s|^SITE_ADDRESS=.*|SITE_ADDRESS=${DOMAIN}|" .env; fi
fi

# свои данные сайта: не в git, обновления их не трогают
if [ ! -f public/config.local.js ] || [ "${1:-}" = "config" ]; then
  echo "Данные для кнопок сайта (можно с @, Enter = пропустить):"
  read -rp "Юзернейм бота: " BOT
  read -rp "Аккаунт менеджера для связи: " MANAGER
  read -rp "Ссылка на канал (https://t.me/...): " CHANNEL
  BOT="${BOT#@}"; MANAGER="${MANAGER#@}"
  cat > public/config.local.js <<JS
// Свои данные сайта. Поменять: ./deploy.sh config  (или отредактировать этот файл)
window.SITE = Object.assign(window.SITE || {}, {
  bot: "${BOT}",
  manager: "${MANAGER}",
  channel: "${CHANNEL}",
});
JS
  echo "Сохранено в public/config.local.js"
fi

# подтягиваем свежую версию, если папка склонирована из git
git -C .. pull --ff-only 2>/dev/null || true

docker compose up -d
docker compose restart web >/dev/null
docker compose ps
. ./.env
if [ -n "${SITE_ADDRESS:-}" ]; then
  echo "✅ Сайт: https://${SITE_ADDRESS}"
else
  echo "✅ Сайт: http://$(curl -4 -fsS https://api.ipify.org 2>/dev/null || echo IP_сервера)"
fi
