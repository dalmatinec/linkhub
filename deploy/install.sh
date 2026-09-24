#!/usr/bin/env bash
# Установка, обновление или восстановление бота на сервере Ubuntu/Debian. Запускать от root:
#   bash /opt/linkhub/deploy/install.sh                        установить или обновить
#   bash /opt/linkhub/deploy/install.sh /root/backup_XXXX.zip  установить и восстановить всё из бэкапа
# Токен и ID владельца спросит один раз и запишет в /opt/linkhub/.env
set -euo pipefail

DIR=/opt/linkhub
cd "$DIR" || { echo "Сначала: git clone https://github.com/dalmatinec/linkhub $DIR"; exit 1; }

if ! python3 -c "import venv, ensurepip" 2>/dev/null; then
    apt-get update -qq && apt-get install -y -qq python3-venv
fi
id linkhub >/dev/null 2>&1 || useradd --system --home "$DIR" --shell /usr/sbin/nologin linkhub

[ -d .venv ] || python3 -m venv .venv
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -r requirements.txt

if [ ! -f .env ]; then
    read -rp "Токен бота от @BotFather: " TOKEN
    read -rp "Telegram ID владельца (несколько через запятую): " OWNERS
    printf 'BOT_TOKEN=%s\nOWNER_IDS=%s\nDATA_DIR=data\nLOG_LEVEL=INFO\n' "$TOKEN" "$OWNERS" > .env
fi
mkdir -p data

systemctl stop linkhub 2>/dev/null || true
if [ $# -ge 1 ]; then
    .venv/bin/python -m bot.restore "$1"
fi

chown -R linkhub:linkhub data
chown linkhub:linkhub .env && chmod 600 .env
cp deploy/linkhub.service /etc/systemd/system/linkhub.service
systemctl daemon-reload
systemctl enable --now linkhub
sleep 3
systemctl --no-pager --lines=5 status linkhub || true
echo
echo "Готово. Логи: journalctl -u linkhub -f"
