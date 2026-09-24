#!/usr/bin/env bash
# Деплой MG Group CRM на Ubuntu/Debian VPS + домен (hoster.by).
# Запуск от root:  sudo bash deploy/deploy.sh crm.ваш-домен.by
set -euo pipefail

DOMAIN="${1:-}"
APP_DIR="${APP_DIR:-/opt/mg-crm}"
SERVICE_USER="${SERVICE_USER:-www-data}"
REPO_SRC="$(cd "$(dirname "$0")/.." && pwd)"

if [[ -z "$DOMAIN" ]]; then
  echo "Использование: sudo bash deploy/deploy.sh crm.ваш-домен.by"
  echo "Пример:        sudo bash deploy/deploy.sh crm.mggroup.by"
  exit 1
fi

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Запускайте от root: sudo bash deploy/deploy.sh $DOMAIN"
  exit 1
fi

echo "==> Домен: $DOMAIN"
echo "==> Каталог: $APP_DIR"

export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y \
  python3 python3-venv python3-pip \
  nginx certbot python3-certbot-nginx \
  curl ca-certificates git \
  fonts-liberation libasound2t64 libatk-bridge2.0-0 libatk1.0-0 \
  libcups2 libdbus-1-3 libdrm2 libgbm1 libgtk-3-0 libnspr4 libnss3 \
  libx11-xcb1 libxcomposite1 libxdamage1 libxrandr2 xdg-utils \
  || apt-get install -y \
  python3 python3-venv python3-pip nginx certbot python3-certbot-nginx \
  curl ca-certificates git

# Node 20 (для сборки фронта)
if ! command -v node >/dev/null 2>&1 || [[ "$(node -v | cut -d. -f1 | tr -d v)" -lt 18 ]]; then
  curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
  apt-get install -y nodejs
fi

id -u "$SERVICE_USER" >/dev/null 2>&1 || useradd -r -m -d "$APP_DIR" -s /usr/sbin/nologin "$SERVICE_USER"

echo "==> Копирую проект в $APP_DIR"
mkdir -p "$APP_DIR"
rsync -a --delete \
  --exclude '.git' \
  --exclude '.venv' \
  --exclude '.venv-mac' \
  --exclude 'frontend/node_modules' \
  --exclude 'data/chrome-cdp-profile' \
  --exclude 'data/chrome-profile' \
  --exclude 'data/chrome-profile-export' \
  --exclude 'data/chrome-profile-export-mac' \
  --exclude '__pycache__' \
  --exclude '.pycache' \
  --exclude 'tools/*.exe' \
  "$REPO_SRC/" "$APP_DIR/"

if [[ ! -f "$APP_DIR/.env" ]]; then
  if [[ -f "$APP_DIR/deploy/env.example" ]]; then
    cp "$APP_DIR/deploy/env.example" "$APP_DIR/.env"
  else
    cat > "$APP_DIR/.env" <<'EOF'
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
POLL_INTERVAL_MINUTES=30
MAX_PAGES=0
HEADLESS=true
CRM_PORT=8080
CRM_HOST=127.0.0.1
EOF
  fi
  echo "Создан $APP_DIR/.env — проверьте TELEGRAM_BOT_TOKEN"
fi

# Всегда слушаем localhost — снаружи только nginx
sed -i 's/^CRM_HOST=.*/CRM_HOST=127.0.0.1/' "$APP_DIR/.env" || true
grep -q '^CRM_HOST=' "$APP_DIR/.env" || echo 'CRM_HOST=127.0.0.1' >> "$APP_DIR/.env"
grep -q '^CRM_PORT=' "$APP_DIR/.env" || echo 'CRM_PORT=8080' >> "$APP_DIR/.env"
grep -q '^HEADLESS=' "$APP_DIR/.env" || echo 'HEADLESS=true' >> "$APP_DIR/.env"

echo "==> Python venv"
python3 -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/pip" install --upgrade pip
"$APP_DIR/.venv/bin/pip" install -r "$APP_DIR/requirements.txt"
mkdir -p "$APP_DIR/.pw-browsers"
PLAYWRIGHT_BROWSERS_PATH="$APP_DIR/.pw-browsers" \
  "$APP_DIR/.venv/bin/playwright" install chromium

echo "==> Сборка frontend"
cd "$APP_DIR/frontend"
npm install
npm run build
cd "$APP_DIR"

mkdir -p "$APP_DIR/data"
chown -R "$SERVICE_USER:$SERVICE_USER" "$APP_DIR"

echo "==> systemd"
sed "s|/opt/mg-crm|$APP_DIR|g; s|User=www-data|User=$SERVICE_USER|; s|Group=www-data|Group=$SERVICE_USER|" \
  "$APP_DIR/deploy/mg-crm.service" > /etc/systemd/system/mg-crm.service
systemctl daemon-reload
systemctl enable mg-crm
systemctl restart mg-crm

echo "==> nginx"
NGINX_CONF=/etc/nginx/sites-available/mg-crm
sed "s/CRM_DOMAIN/$DOMAIN/g" "$APP_DIR/deploy/nginx.conf.template" > "$NGINX_CONF"
ln -sfn "$NGINX_CONF" /etc/nginx/sites-enabled/mg-crm
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl reload nginx

echo "==> SSL (Let's Encrypt)"
if certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos --register-unsafely-without-email --redirect; then
  echo "HTTPS готов: https://$DOMAIN"
else
  echo ""
  echo "!!! Certbot не выдал сертификат."
  echo "    Обычно DNS ещё не указывает на этот сервер."
  echo "    После настройки A-записи в hoster.by выполните:"
  echo "    sudo certbot --nginx -d $DOMAIN"
fi

SERVER_IP="$(curl -4 -fsS ifconfig.me 2>/dev/null || curl -4 -fsS icanhazip.com 2>/dev/null || hostname -I | awk '{print $1}')"
echo ""
echo "============================================"
echo " Готово (или почти)."
echo " Домен:     https://$DOMAIN"
echo " IP сервера: $SERVER_IP"
echo ""
echo " В hoster.by → DNS домена создайте:"
echo "   Тип: A"
echo "   Хост: $( [[ "$DOMAIN" == *.* ]] && echo "${DOMAIN%%.*}" || echo '@' )   (для поддомена crm.example.by → crm; для корня → @)"
echo "   Значение: $SERVER_IP"
echo "   TTL: 300"
echo ""
echo " Проверка:"
echo "   systemctl status mg-crm"
echo "   curl -I http://127.0.0.1:8080"
echo "   curl -I https://$DOMAIN"
echo "============================================"
