#!/usr/bin/env bash
# Установка и запуск в одну команду: ./setup.sh
set -euo pipefail
cd "$(dirname "$0")"

green() { printf "\033[32m%s\033[0m\n" "$*"; }
yellow() { printf "\033[33m%s\033[0m\n" "$*"; }

# 1. Docker
if ! command -v docker >/dev/null 2>&1; then
  yellow "Docker не найден, устанавливаю..."
  curl -fsSL https://get.docker.com | sh
fi
if ! docker compose version >/dev/null 2>&1; then
  echo "Нужен Docker Compose v2 (команда «docker compose»). Обновите Docker." >&2
  exit 1
fi

# 2. Настройки
set_env() {
  local key="$1" value="$2"
  if grep -q "^${key}=" .env; then
    sed -i "s|^${key}=.*|${key}=${value}|" .env
  else
    echo "${key}=${value}" >> .env
  fi
}

if [ ! -f .env ]; then
  cp .env.example .env
  green "Настройка бота (Enter, чтобы пропустить необязательное)"
  read -rp "Токен бота от @BotFather: " BOT_TOKEN
  read -rp "Ваш Telegram id (у @userinfobot): " ADMIN_IDS
  read -rp "Название магазина [Satpaev]: " BRAND_NAME
  read -rp "Канал (@username или -100...): " CHANNEL_ID
  read -rp "TG_API_ID для постинга от аккаунта (my.telegram.org): " TG_API_ID
  read -rp "TG_API_HASH: " TG_API_HASH
  set_env BOT_TOKEN "$BOT_TOKEN"
  set_env ADMIN_IDS "$ADMIN_IDS"
  set_env BRAND_NAME "${BRAND_NAME:-Satpaev}"
  set_env CHANNEL_ID "$CHANNEL_ID"
  set_env TG_API_ID "$TG_API_ID"
  set_env TG_API_HASH "$TG_API_HASH"
fi

if ! grep -q "^POSTGRES_PASSWORD=." .env; then
  set_env POSTGRES_PASSWORD "$(tr -dc 'A-Za-z0-9' </dev/urandom | head -c 32)"
fi
chmod 600 .env

# 3. Папки (бот и постер работают не от root, uid 1000)
mkdir -p backups data/shared/media data/poster data/redis
chown -R 1000:1000 backups data/shared data/poster 2>/dev/null || true
chmod 700 data/poster

# 4. Запуск
docker compose up -d --build
green "Бот запущен."

# 5. Вход в аккаунт для постинга
if grep -q "^TG_API_ID=[0-9]" .env && [ ! -f data/poster/poster.session ]; then
  read -rp "Войти в аккаунт для постинга в канал сейчас? [y/N] " ans
  if [[ "${ans:-n}" =~ ^[Yy]$ ]]; then
    docker compose run --rm poster python -m poster login
    docker compose restart poster
  else
    yellow "Позже: docker compose run --rm poster python -m poster login"
  fi
fi

docker compose ps
green "Готово. Откройте бота в Telegram и нажмите /start"
