# Голосовой чат через Ubuntu

Стример запускает обычное приложение. Ты запускаешь `run-chat.bat`. Сообщения идут через этот релей, Windows на ПК стримера читает их системным голосом.

## На сервере

```bash
# скопируй папку server/ на Ubuntu, затем:
sed -i 's/\r$//' install.sh voice_relay.py voice-relay.service
sudo bash install.sh
```

Если `apt-get update` ругается на `repo.virtuozzo.com` / 403 — это репозиторий хостера, не наш скрипт. Новый `install.sh` это пропускает. Или поставь без apt:

```bash
python3 -m venv /opt/cs2-voice/venv
/opt/cs2-voice/venv/bin/pip install 'websockets>=13.0'
```

Скрипт поставит сервис, откроет порт **8766** и напечатает:

- адрес вида `ws://IP:8766`
- ключ

Этот же ключ вставь и стримеру, и себе.

Ручной запуск без systemd:

```bash
python3 -m venv venv
source venv/bin/activate
pip install 'websockets>=13.0'
export VOICE_RELAY_TOKEN='твой-ключ'
python3 voice_relay.py --port 8766
```

Проверка на своём ПК без Ubuntu:

```bat
python server/voice_relay.py --token test --port 8766
```

Тогда адрес: `ws://127.0.0.1:8766`, ключ: `test`.

## В программе

1. Стример: вкладка **Голос** → адрес + ключ → громкость → **Слушать чат**.
2. Ты: `run-chat.bat` → те же адрес и ключ → пишешь «Привет».
3. У стримера должен сыграть голос Windows (обычно Ирина, если стоит русский языковой пакет).

## Доступ и админка (порт 8767)

Отдельный API: регистрация, вход, выдача доступа на срок.

```bash
# на VPS: скопируй папку server/ (scp / git clone), затем:
cd server
sed -i 's/\r$//' install_access.sh access_api.py access-api.service
sudo ACCESS_ADMIN_PASSWORD='твой_пароль' bash install_access.sh
curl -s http://127.0.0.1:8767/health
```

Скрипт сам создаст `/opt/cs2-access`, `admin.secret`, systemd и напечатает URL для `config.json`.

Первый запуск создаёт админа **Rundelman**. Пароль генерируется и пишется **только** в `admin.secret` рядом с базой (или задай `ACCESS_ADMIN_PASSWORD` / положи пароль в `admin.secret` до первого запуска). **Не коммить этот файл.**

```bash
# свой пароль до первого запуска:
echo -n 'твой_пароль' | sudo tee /opt/cs2-access/admin.secret
sudo chmod 600 /opt/cs2-access/admin.secret
```

В `config.json` у клиента:

```json
"access": {
  "enabled": true,
  "server": "http://IP_СЕРВЕРА:8767"
}
```

Пользователь: **Регистрация** → ник и пароль → в админке появится в списке → админ **Выдать доступ** на N дней.

Админ: обычный **Вход** под логином админа — откроется панель пользователей.

Покупателям раздавай `dist/CS2DonateInteract.exe` (сборка: `build_exe.bat`).

Отключить вход для своей разработки: `"access": { "enabled": false }`.
