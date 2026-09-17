#!/usr/bin/env bash
set -euo pipefail

ROOT=/opt/cs2-access
HERE="$(cd "$(dirname "$0")" && pwd)"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Запусти: sudo bash install_access.sh"
  exit 1
fi

if [[ ! -f "$HERE/access_api.py" ]]; then
  echo "Рядом с install_access.sh нет access_api.py. Клади всю папку server/ на VPS."
  exit 1
fi

command -v python3 >/dev/null 2>&1 || {
  apt-get update -y || true
  DEBIAN_FRONTEND=noninteractive apt-get install -y python3
}

mkdir -p "$ROOT"
cp "$HERE/access_api.py" "$ROOT/access_api.py"
chmod 755 "$ROOT/access_api.py"

if [[ ! -f "$ROOT/admin.secret" ]]; then
  if [[ -n "${ACCESS_ADMIN_PASSWORD:-}" ]]; then
    printf '%s' "$ACCESS_ADMIN_PASSWORD" >"$ROOT/admin.secret"
  else
    echo "Задай пароль админа (логин по умолчанию Rundelman):"
    read -rs ADMIN_PW
    echo
    if [[ -z "$ADMIN_PW" ]]; then
      ADMIN_PW="$(python3 -c 'import secrets; print(secrets.token_urlsafe(14))')"
      echo "Пароль не введён — сгенерирован случайный, смотри $ROOT/admin.secret"
    fi
    printf '%s' "$ADMIN_PW" >"$ROOT/admin.secret"
  fi
  chmod 600 "$ROOT/admin.secret"
  echo "Пароль админа: $ROOT/admin.secret"
fi

cat >/etc/cs2-access.env <<EOF
ACCESS_DB=${ROOT}/access.db
ACCESS_ADMIN_SECRET=${ROOT}/admin.secret
ACCESS_ADMIN_USER=Rundelman
ACCESS_PORT=8767
ACCESS_HOST=0.0.0.0
EOF
chmod 600 /etc/cs2-access.env

if [[ -d /run/systemd/system ]] && command -v systemctl >/dev/null 2>&1; then
  sed "s|/opt/cs2-access|${ROOT}|g" "$HERE/access-api.service" >/etc/systemd/system/access-api.service
  if ! grep -q EnvironmentFile /etc/systemd/system/access-api.service; then
    sed -i '/\[Service\]/a EnvironmentFile=/etc/cs2-access.env' /etc/systemd/system/access-api.service
  fi
  systemctl daemon-reload
  systemctl enable --now access-api
  systemctl --no-pager --full status access-api || true
else
  echo "systemd нет — запуск в фоне."
  pkill -f "${ROOT}/access_api.py" 2>/dev/null || true
  set -a
  # shellcheck source=/dev/null
  source /etc/cs2-access.env
  set +a
  nohup python3 "$ROOT/access_api.py" --host 0.0.0.0 --port 8767 >/var/log/cs2-access.log 2>&1 &
  echo $! >/var/run/cs2-access.pid
  echo "лог: /var/log/cs2-access.log"
fi

if command -v ufw >/dev/null 2>&1; then
  ufw allow 8767/tcp || true
fi
iptables -C INPUT -p tcp --dport 8767 -j ACCEPT 2>/dev/null || \
  iptables -I INPUT -p tcp --dport 8767 -j ACCEPT 2>/dev/null || true

IP="$(curl -4 -fsS --max-time 8 ifconfig.me 2>/dev/null || wget -qO- -T 8 -4 ifconfig.me 2>/dev/null || hostname -I | awk '{print $1}')"
echo
echo "Готово."
echo "В config.json на ПК стримера:"
echo '  "access": { "enabled": true, "server": "http://'"${IP}"':8767" }'
echo
echo "Проверка с VPS: curl -s http://127.0.0.1:8767/health"
echo "Админ: логин Rundelman, пароль из ${ROOT}/admin.secret"
echo "Если с ПК не коннектится — открой TCP 8767 в панели Jino."
