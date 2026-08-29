#!/usr/bin/env bash
set -euo pipefail

ROOT=/opt/cs2-voice
HERE="$(cd "$(dirname "$0")" && pwd)"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Запусти: sudo bash install.sh"
  exit 1
fi

if [[ ! -f "$HERE/voice_relay.py" ]]; then
  echo "Рядом с install.sh нет voice_relay.py. Клади всю папку server/."
  exit 1
fi

python_ready() {
  command -v python3 >/dev/null 2>&1 && python3 -c "import venv" 2>/dev/null
}

if ! python_ready; then
  echo "Ставлю python3. apt update может ругнуться на Virtuozzo — это не страшно."
  apt-get update -y || true
  DEBIAN_FRONTEND=noninteractive apt-get install -y python3 python3-venv python3-pip
fi

if ! python_ready; then
  echo "Нет python3 или модуля venv. Поставь вручную:"
  echo "  apt-get install -y python3 python3-venv"
  exit 1
fi

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
  TOKEN="$(grep '^VOICE_RELAY_TOKEN=' /etc/cs2-voice.env | cut -d= -f2- | tr -d '\r')"
fi

if [[ -d /run/systemd/system ]] && command -v systemctl >/dev/null 2>&1; then
  cp "$HERE/voice-relay.service" /etc/systemd/system/voice-relay.service
  systemctl daemon-reload
  systemctl enable --now voice-relay
  systemctl --no-pager --full status voice-relay || true
else
  echo "systemd в этом контейнере нет — запускаю релей в фоне."
  pkill -f /opt/cs2-voice/voice_relay.py 2>/dev/null || true
  nohup "$ROOT/venv/bin/python" "$ROOT/voice_relay.py" --host 0.0.0.0 \
    >/var/log/cs2-voice.log 2>&1 &
  echo $! >/var/run/cs2-voice.pid
  echo "лог: /var/log/cs2-voice.log"
fi

if command -v ufw >/dev/null 2>&1; then
  ufw allow 8766/tcp || true
fi
iptables -C INPUT -p tcp --dport 8766 -j ACCEPT 2>/dev/null || \
  iptables -I INPUT -p tcp --dport 8766 -j ACCEPT 2>/dev/null || true

IP="$(curl -4 -fsS --max-time 8 ifconfig.me 2>/dev/null || wget -qO- -T 8 -4 ifconfig.me 2>/dev/null || hostname -I | awk '{print $1}')"
echo
echo "Готово."
echo "Адрес для программы:  ws://${IP}:8766"
echo "Ключ:                 ${TOKEN}"
echo
echo "Вставь оба поля у стримера (вкладка Голос) и у себя (run-chat.bat)."
echo "Если связи нет — открой TCP 8766 ещё в панели хостера."
