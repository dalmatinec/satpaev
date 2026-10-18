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
  echo "Данные для кнопок сайта (можно с @, Enter = оставить как есть):"
  read -rp "Юзернейм бота [satboxbot]: " BOT
  read -rp "Аккаунт менеджера [tonkeeper_8]: " MANAGER
  read -rp "Ссылка на канал (https://t.me/...): " CHANNEL
  BOT="${BOT#@}"; MANAGER="${MANAGER#@}"
  BOT="${BOT:-satboxbot}"; MANAGER="${MANAGER:-tonkeeper_8}"
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

# если порт уже занят чужой программой (nginx, другой сайт), берём свободный
port_busy() { ss -ltnH "sport = :$1" 2>/dev/null | grep -q . ; }
. ./.env
HTTP_PORT="${HTTP_PORT:-80}"
if ! docker compose ps --status running -q web 2>/dev/null | grep -q . && port_busy "${HTTP_PORT}"; then
  for p in 8080 8081 8082 8088 8090; do
    if ! port_busy "$p"; then
      echo "⚠️ Порт ${HTTP_PORT} занят другой программой, сайт будет на порту ${p}"
      sed -i "s|^HTTP_PORT=.*|HTTP_PORT=${p}|" .env
      grep -q "^HTTP_PORT=" .env || echo "HTTP_PORT=${p}" >> .env
      HTTP_PORT=$p
      break
    fi
  done
  if port_busy 443; then sed -i "s|^HTTPS_PORT=.*|HTTPS_PORT=8443|" .env; fi
fi

docker compose up -d
docker compose restart web >/dev/null
docker compose ps
if [ -n "${SITE_ADDRESS:-}" ]; then
  echo "✅ Сайт: https://${SITE_ADDRESS}"
else
  IP="$(curl -4 -fsS https://api.ipify.org 2>/dev/null || echo IP_сервера)"
  if [ "${HTTP_PORT}" = "80" ]; then echo "✅ Сайт: http://${IP}"; else echo "✅ Сайт: http://${IP}:${HTTP_PORT}"; fi
fi
