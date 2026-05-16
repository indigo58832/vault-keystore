#!/bin/bash
# Запуск KeyStore. Кладёт лог в /tmp/keystore.log.
cd "$(dirname "$(readlink -f "$0")")"
exec python3 -m keystore "$@" >> /tmp/keystore.log 2>&1
