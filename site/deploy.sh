#!/usr/bin/env bash
# Запуск сайта: ./deploy.sh
# Обновление: git -C .. pull && ./deploy.sh
#   ./deploy.sh config   поменять бота, менеджера и канал
#   ./deploy.sh domain   указать домен (например satbox.duckdns.org) и выпустить SSL
#
# Если на сервере уже работает nginx (занимает 80/443), сайт подключается к нему,
# а SSL выпускает certbot. Если nginx нет, сайт поднимается в Docker на Caddy с авто SSL.
set -euo pipefail
cd "$(dirname "$0")"
SITE_DIR="$(pwd)"
WEB_ROOT=/var/www/satpaev-site
NGINX_CONF=satpaev-site.conf

set_env() {
  if grep -q "^$1=" .env; then sed -i "s|^$1=.*|$1=$2|" .env; else echo "$1=$2" >> .env; fi
}

[ -f .env ] || cp .env.example .env
# shellcheck disable=SC1091
. ./.env

if [ -z "${SITE_ADDRESS:-}" ] || [ "${1:-}" = "domain" ]; then
  read -rp "Домен сайта, например satbox.duckdns.org (Enter, если пока нет): " DOMAIN
  if [ -n "${DOMAIN}" ]; then
    read -rp "Почта для SSL (Enter, чтобы пропустить): " EMAIL
    set_env SITE_ADDRESS "${DOMAIN}"
    set_env SSL_EMAIL "${EMAIL}"
  fi
  . ./.env
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

IP="$(curl -4 -fsS https://api.ipify.org 2>/dev/null || echo IP_сервера)"

if systemctl is-active --quiet nginx 2>/dev/null; then
  # ===== режим nginx: на сервере уже есть nginx =====
  echo "Найден nginx, подключаю сайт к нему."
  docker compose down >/dev/null 2>&1 || true
  mkdir -p "${WEB_ROOT}"
  cp -a "${SITE_DIR}/public/." "${WEB_ROOT}/"
  chmod -R a+rX "${WEB_ROOT}"

  if [ -n "${SITE_ADDRESS:-}" ]; then LISTEN="listen 80; listen [::]:80;"; NAME="${SITE_ADDRESS}"
  else LISTEN="listen 8080; listen [::]:8080;"; NAME="_"; fi

  if [ -d /etc/nginx/sites-available ]; then
    CONF_PATH=/etc/nginx/sites-available/${NGINX_CONF}
  else
    CONF_PATH=/etc/nginx/conf.d/${NGINX_CONF}
  fi
  # если certbot уже вписал SSL в конфиг, не затираем его
  if [ -f "${CONF_PATH}" ] && grep -q "managed by Certbot" "${CONF_PATH}" && grep -q "server_name ${NAME};" "${CONF_PATH}"; then
    echo "Конфиг nginx с SSL уже есть, обновляю только файлы сайта."
  else
    cat > "${CONF_PATH}" <<NGINX
server {
    ${LISTEN}
    server_name ${NAME};
    root ${WEB_ROOT};
    index index.html;

    server_tokens off;
    add_header X-Content-Type-Options nosniff always;
    add_header X-Frame-Options SAMEORIGIN always;
    add_header Referrer-Policy strict-origin-when-cross-origin always;

    gzip on;
    gzip_types text/css application/javascript image/svg+xml;

    location ~* \.(css|js|svg|png|jpg|webp|woff2)\$ {
        expires 7d;
        add_header Cache-Control "public";
    }
    location / {
        try_files \$uri \$uri/ /index.html;
    }
}
NGINX
  fi
  if [ -d /etc/nginx/sites-enabled ]; then ln -sf "${CONF_PATH}" /etc/nginx/sites-enabled/${NGINX_CONF}; fi
  nginx -t
  systemctl reload nginx

  if [ -n "${SITE_ADDRESS:-}" ]; then
    if ! command -v certbot >/dev/null 2>&1; then
      apt-get update -qq && apt-get install -y -qq certbot python3-certbot-nginx
    fi
    if [ -n "${SSL_EMAIL:-}" ]; then MAIL=(-m "${SSL_EMAIL}"); else MAIL=(--register-unsafely-without-email); fi
    certbot --nginx -d "${SITE_ADDRESS}" --non-interactive --agree-tos "${MAIL[@]}" --redirect --keep-until-expiring
    echo "✅ Сайт: https://${SITE_ADDRESS}  (сертификат продлевается сам)"
  else
    command -v ufw >/dev/null 2>&1 && ufw allow 8080/tcp >/dev/null 2>&1 || true
    echo "✅ Сайт: http://${IP}:8080"
    echo "   Для https без порта: ./deploy.sh domain"
  fi
  exit 0
fi

# ===== режим Docker + Caddy: nginx на сервере нет =====
if ! command -v docker >/dev/null 2>&1; then
  echo "Docker не найден, устанавливаю..."
  curl -fsSL https://get.docker.com | sh
fi
HTTP_PORT="${HTTP_PORT:-80}"
port_busy() { ss -ltnH "sport = :$1" 2>/dev/null | grep -q . ; }
if ! docker compose ps --status running -q web 2>/dev/null | grep -q . && port_busy "${HTTP_PORT}"; then
  for p in 8080 8081 8082 8088 8090; do
    if ! port_busy "$p"; then
      echo "⚠️ Порт ${HTTP_PORT} занят, сайт будет на порту ${p}"
      set_env HTTP_PORT "$p"; HTTP_PORT=$p
      break
    fi
  done
  if port_busy 443; then set_env HTTPS_PORT 8443; fi
fi
command -v ufw >/dev/null 2>&1 && ufw allow "${HTTP_PORT}/tcp" >/dev/null 2>&1 || true
docker compose up -d
docker compose restart web >/dev/null
docker compose ps
if [ -n "${SITE_ADDRESS:-}" ]; then
  echo "✅ Сайт: https://${SITE_ADDRESS}"
elif [ "${HTTP_PORT}" = "80" ]; then
  echo "✅ Сайт: http://${IP}"
else
  echo "✅ Сайт: http://${IP}:${HTTP_PORT}"
fi
