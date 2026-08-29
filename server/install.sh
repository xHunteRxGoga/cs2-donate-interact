#!/usr/bin/env bash
set -euo pipefail

ROOT=/opt/cs2-voice
HERE="$(cd "$(dirname "$0")" && pwd)"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Запусти: sudo bash install.sh"
  exit 1
fi

apt-get update -y
apt-get install -y python3 python3-venv python3-pip

mkdir -p "$ROOT"
python3 -m venv "$ROOT/venv"
"$ROOT/venv/bin/pip" install -U pip
"$ROOT/venv/bin/pip" install "websockets>=13.0"

cp "$HERE/voice_relay.py" "$ROOT/voice_relay.py"

if [[ ! -f /etc/cs2-voice.env ]]; then
  TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(18))')"
  cat >/etc/cs2-voice.env <<EOF
VOICE_RELAY_TOKEN=${TOKEN}
VOICE_RELAY_PORT=8766
VOICE_RELAY_HOST=0.0.0.0
EOF
  chmod 600 /etc/cs2-voice.env
  echo "Ключ записан в /etc/cs2-voice.env"
else
  TOKEN="$(grep VOICE_RELAY_TOKEN /etc/cs2-voice.env | cut -d= -f2-)"
fi

cp "$HERE/voice-relay.service" /etc/systemd/system/voice-relay.service
systemctl daemon-reload
systemctl enable --now voice-relay

if command -v ufw >/dev/null 2>&1; then
  ufw allow 8766/tcp || true
fi

IP="$(curl -4 -s ifconfig.me || hostname -I | awk '{print $1}')"
echo
echo "Готово."
echo "Адрес для программы:  ws://${IP}:8766"
echo "Ключ:                 ${TOKEN}"
echo
echo "Вставь оба поля у стримера (вкладка Голос) и у себя (run-chat.bat)."
