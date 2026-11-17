#!/usr/bin/env bash
# Связать Бакси с модератором (dalmatinec/baxi-guard) на этом сервере. Запускать от root, можно повторно:
#   bash /opt/linkhub/deploy/guard-link.sh
# Что делает: берёт общий ключ BAXI_API_KEY из .env модератора (или из .env Бакси, или создаёт новый),
# прописывает его и адреса в оба .env (оба API только на 127.0.0.1) и перезапускает оба бота.
# Ключ на экран не выводится.
set -euo pipefail
BAXI=/opt/linkhub/.env
GUARD=/opt/baxi-guard/.env
[ -f "$BAXI" ] || { echo "Нет $BAXI: сначала поставь Бакси"; exit 1; }
[ -f "$GUARD" ] || { echo "Нет $GUARD: сначала поставь модератора (bash /opt/baxi-guard/deploy/install.sh)"; exit 1; }

get_env() { grep "^$1=" "$2" 2>/dev/null | head -1 | cut -d= -f2- || true; }
set_env() {  # set_env ФАЙЛ КЛЮЧ ЗНАЧЕНИЕ: заменить строку или дописать
    FILE="$1" KEY="$2" VALUE="$3" python3 - <<'PY'
import os, re
path, key, value = os.environ["FILE"], os.environ["KEY"], os.environ["VALUE"]
text = open(path, encoding="utf-8").read()
if re.search(rf"^{re.escape(key)}=", text, flags=re.M):
    text = re.sub(rf"^{re.escape(key)}=.*$", lambda _m: f"{key}={value}", text, flags=re.M)
else:
    text = text.rstrip("\n") + f"\n{key}={value}\n"
open(path, "w", encoding="utf-8").write(text)
PY
}

KEY=$(get_env BAXI_API_KEY "$GUARD")
[ -n "$KEY" ] || KEY=$(get_env BAXI_API_KEY "$BAXI")
[ -n "$KEY" ] || KEY=$(python3 -c 'import secrets; print(secrets.token_hex(24))')

set_env "$BAXI" BAXI_API_KEY "$KEY"
set_env "$BAXI" BAXI_API_PORT 8710
set_env "$BAXI" GUARD_API_URL http://127.0.0.1:8711
set_env "$GUARD" BAXI_API_KEY "$KEY"
set_env "$GUARD" GUARD_API_PORT 8711
set_env "$GUARD" BAXI_API_URL http://127.0.0.1:8710
# модератору нужен ID Бакси, чтобы не перебивать его /settings
BAXI_TOKEN=$(get_env BOT_TOKEN "$BAXI")
[ -n "$(get_env BAXI_BOT_ID "$GUARD")" ] || set_env "$GUARD" BAXI_BOT_ID "${BAXI_TOKEN%%:*}"

chmod 600 "$BAXI" "$GUARD"
systemctl restart linkhub
systemctl restart baxi-guard
sleep 3
for port in 8710 8711; do
    if ss -ltn 2>/dev/null | grep -q "127.0.0.1:$port"; then echo "✅ 127.0.0.1:$port слушает"; else echo "⚠️ 127.0.0.1:$port не слушает, смотри логи"; fi
done
echo "Готово: боты связаны. Логи: journalctl -u linkhub -n 30   journalctl -u baxi-guard -n 30"
