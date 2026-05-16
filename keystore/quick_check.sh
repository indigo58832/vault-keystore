#!/bin/bash
# Toggle: одна и та же клавиша открывает и закрывает окно.
PIDFILE="/tmp/quick_check.pid"

# Если PID есть и процесс жив — убиваем (toggle off)
if [ -f "$PIDFILE" ]; then
    OLDPID=$(cat "$PIDFILE" 2>/dev/null)
    if [ -n "$OLDPID" ] && kill -0 "$OLDPID" 2>/dev/null; then
        kill "$OLDPID" 2>/dev/null
        rm -f "$PIDFILE"
        exit 0
    fi
    rm -f "$PIDFILE"
fi

# Не запущен — стартуем в отдельной сессии (чтобы не умер вместе с родителем)
cd "$(dirname "$(readlink -f "$0")")"
setsid -f python3 -m keystore.quick_check > /tmp/quick_check.log 2>&1 < /dev/null

# Дадим процессу секунду подняться, потом запомним его PID
sleep 0.4
pgrep -f "python3 -m keystore.quick_check" | head -1 > "$PIDFILE"
