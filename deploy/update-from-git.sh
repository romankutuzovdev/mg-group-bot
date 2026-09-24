#!/usr/bin/env bash
# Обновление бота на сервере из GitHub (вызывать из CI или вручную).
# Пример: sudo bash /opt/mg-crm/deploy/update-from-git.sh
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/mg-crm}"
BRANCH="${BRANCH:-main}"
SERVICE_USER="${SERVICE_USER:-www-data}"

cd "$APP_DIR"

echo "==> git fetch/pull ($BRANCH)"
git fetch --all --prune
git checkout "$BRANCH"
git reset --hard "origin/$BRANCH"

echo "==> Python deps"
if [[ ! -d "$APP_DIR/.venv" ]]; then
  python3 -m venv "$APP_DIR/.venv"
fi
"$APP_DIR/.venv/bin/pip" install -q --upgrade pip
"$APP_DIR/.venv/bin/pip" install -q -r "$APP_DIR/requirements.txt"

echo "==> Frontend build"
cd "$APP_DIR/frontend"
npm ci --omit=dev 2>/dev/null || npm install
npm run build
cd "$APP_DIR"

# .env на сервере не трогаем (секреты только там)
mkdir -p "$APP_DIR/data"
chown -R "$SERVICE_USER:$SERVICE_USER" "$APP_DIR"

echo "==> restart mg-crm"
systemctl restart mg-crm
systemctl --no-pager --full status mg-crm | head -20
echo "Готово."
