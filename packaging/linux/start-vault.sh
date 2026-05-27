#!/bin/bash
# Запуск portable-сборки Vault (Linux). Положи рядом VaultLauncher или вызывай из каталога сборки.
set -euo pipefail
DIR="$(dirname "$(readlink -f "$0")")"
if [[ -x "$DIR/VaultLauncher" ]]; then
  exec "$DIR/VaultLauncher"
fi
if [[ -x "$DIR/Vault" && -x "$DIR/KeyCheckerServer" ]]; then
  "$DIR/KeyCheckerServer" --port 17777 &
  SERVER_PID=$!
  trap 'kill "$SERVER_PID" 2>/dev/null || true' EXIT
  for _ in $(seq 1 40); do
    if curl -sf "http://127.0.0.1:17777/health" >/dev/null 2>&1; then
      exec "$DIR/Vault"
    fi
    sleep 0.25
  done
  echo "KeyCheckerServer не ответил на :17777" >&2
  exit 1
fi
echo "Не найден VaultLauncher или пара Vault + KeyCheckerServer в $DIR" >&2
exit 1
