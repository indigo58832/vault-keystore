#!/bin/bash
# Показывает окно Vault если запущено, иначе запускает.
# У Obsidian тоже бывает «Vault» в заголовке — поэтому ищем окно где
# заголовок ЗАКАНЧИВАЕТСЯ ровно на "Vault" (а не на "1.12.7" как у Obsidian).

WID=$(wmctrl -l 2>/dev/null | awk '$NF == "Vault" {print $1; exit}')

if [ -n "$WID" ]; then
    wmctrl -ia "$WID"
    exit 0
fi

# Не запущено — стартуем
exec "$(dirname "$(readlink -f "$0")")/start.sh"
