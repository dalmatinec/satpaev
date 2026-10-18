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
# где работает бот: по умолчанию на этом же сервере
API_UPSTREAM="${API_UPSTREAM:-http://127.0.0.1:${API_PORT:-8090}}"
API_UPSTREAM="${API_UPSTREAM%/}"

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

# сборка: копия public в www с новой версией файлов, чтобы браузеры сразу брали свежий CSS и JS
VERSION="$(date +%s)"
rm -rf www && cp -a public www
sed -i "s/__V__/${VERSION}/g" www/index.html

if systemctl is-active --quiet nginx 2>/dev/null; then
  # ===== режим nginx: на сервере уже есть nginx =====
  echo "Найден nginx, подключаю сайт к нему."
  docker compose down >/dev/null 2>&1 || true
  mkdir -p "${WEB_ROOT}"
  cp -a "${SITE_DIR}/www/." "${WEB_ROOT}/"
  chmod -R a+rX "${WEB_ROOT}"

  if [ -n "${SITE_ADDRESS:-}" ]; then LISTEN="listen 80; listen [::]:80;"; NAME="${SITE_ADDRESS}"
  else LISTEN="listen 8080; listen [::]:8080;"; NAME="_"; fi

  if [ -d /etc/nginx/sites-available ]; then
    CONF_PATH=/etc/nginx/sites-available/${NGINX_CONF}
  else
    CONF_PATH=/etc/nginx/conf.d/${NGINX_CONF}
  fi
  mkdir -p /etc/nginx/snippets

  # заголовки безопасности (подключаются в каждый location, иначе nginx их теряет)
  cat > /etc/nginx/snippets/satpaev-headers.conf <<'HDR'
add_header X-Content-Type-Options nosniff always;
add_header Referrer-Policy strict-origin-when-cross-origin always;
add_header Permissions-Policy "camera=(), microphone=(), geolocation=(), payment=()" always;
add_header Strict-Transport-Security "max-age=31536000" always;
add_header Content-Security-Policy "default-src 'self'; script-src 'self'; style-src 'self' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'self' https://web.telegram.org https://*.telegram.org" always;
HDR
  # лимит запросов к API: 2 в секунду с одного IP, всплеск до 20
  cat > /etc/nginx/conf.d/satpaev-ratelimit.conf <<'RL'
limit_req_zone $binary_remote_addr zone=satpaev_api:10m rate=2r/s;
RL

  cat > "${CONF_PATH}" <<NGINX
server {
    ${LISTEN}
    server_name ${NAME};
    root ${WEB_ROOT};
    index index.html;
    server_tokens off;
    client_max_body_size 16k;

    gzip on;
    gzip_types text/css application/javascript application/json image/svg+xml;

    # API бота (только чтение): курсы, цены, тексты, проверка юзернейма
    location ^~ /api/ {
        limit_req zone=satpaev_api burst=20 nodelay;
        limit_req_status 429;
        limit_except GET { deny all; }
        proxy_pass ${API_UPSTREAM};
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_connect_timeout 3s;
        proxy_read_timeout 12s;
        include /etc/nginx/snippets/satpaev-headers.conf;
    }
    location ~ /\.(?!well-known) { deny all; }
    location ~* \.(css|js|svg|png|jpg|webp|woff2)\$ {
        expires 30d;
        add_header Cache-Control "public, immutable";
        include /etc/nginx/snippets/satpaev-headers.conf;
    }
    location / {
        add_header Cache-Control "no-cache";
        include /etc/nginx/snippets/satpaev-headers.conf;
        try_files \$uri \$uri/ /index.html;
    }
}
NGINX
  if [ -d /etc/nginx/sites-enabled ]; then ln -sf "${CONF_PATH}" /etc/nginx/sites-enabled/${NGINX_CONF}; fi
  nginx -t
  systemctl reload nginx

  if [ -n "${SITE_ADDRESS:-}" ]; then
    if ! command -v certbot >/dev/null 2>&1; then
      apt-get update -qq && apt-get install -y -qq certbot python3-certbot-nginx
    fi
    if [ -n "${SSL_EMAIL:-}" ]; then MAIL=(-m "${SSL_EMAIL}"); else MAIL=(--register-unsafely-without-email); fi
    # --reinstall: если сертификат уже есть, он просто подключается к новому конфигу, без перевыпуска
    certbot --nginx -d "${SITE_ADDRESS}" --non-interactive --agree-tos "${MAIL[@]}" --redirect --reinstall
    echo "✅ Сайт: https://${SITE_ADDRESS}  (сертификат продлевается сам)"
  else
    command -v ufw >/dev/null 2>&1 && ufw allow 8080/tcp >/dev/null 2>&1 || true
    echo "✅ Сайт: http://${IP}:8080"
    echo "   Для https без порта: ./deploy.sh domain"
  fi
  curl -fsS -m 5 -o /dev/null "${API_UPSTREAM}/api/health" \
    && echo "✅ Бот отдаёт данные сайту (курсы, цены, тексты)" \
    || echo "⚠️ API бота не отвечает: обновите бота (cd ~/satpaev && git pull && docker compose up -d --build)"
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
set_env API_UPSTREAM "${API_UPSTREAM}"
if [ -n "${SITE_ADDRESS:-}" ]; then set_env CADDY_ADDRESS "${SITE_ADDRESS}"; else set_env CADDY_ADDRESS ":${HTTP_PORT}"; fi
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
