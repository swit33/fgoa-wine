#!/bin/bash
# Локальный сервер FGO (MariaDB + ARTEMiS) под Wine.
#   ./server.sh          поднять то, что ещё не поднято
#   ./server.sh stop     остановить (MariaDB — штатно, через mysqladmin)
# Порты: ALL.Net 777, billing 9999, AimeDB 7777, БД 8889 (8888 занят докером на этой машине).
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
export FGOA_WINE_DIR="$(cd "$HERE/.." && pwd)"
CONFIG="$HOME/.config/fgoa-wine/config.env"
[ -r "$CONFIG" ] && . "$CONFIG"
: "${FGOA_ROOT:=$(cd "$HERE/../.." && pwd)}"
: "${WINEPREFIX:=$HOME/.local/share/fgoa-wine/prefix}"
export FGOA_ROOT WINEPREFIX
ROOT="$FGOA_ROOT"
export WINEDEBUG=-all
WROOT="Z:$(printf '%s' "$ROOT" | tr '/' '\\')"
SRV="$WROOT\\Server"
DB_PORT=8889
HTTP_PORT=777

wait_port() { for _ in $(seq 1 40); do ss -ltn | grep -q ":$1 " && return 0; sleep 1; done; return 1; }
port_up()   { ss -ltn | grep -q ":$1 "; }

# Закрываем БД так же, как их Stop-FGOLocalServer.ps1: mariadb-admin с root-паролем
# из их же скрипта и --no-defaults (иначе [client] из mariadb.ini ломает доступ).
DB_ROOT_PASSWORD=FgoLocalRoot2026

stop_db() {
    port_up "$DB_PORT" || return 0
    wine "$SRV\\mariadb-10.11.16-winx64\\bin\\mariadb-admin.exe" --no-defaults \
        --host=127.0.0.1 --port=$DB_PORT --user=root --password=$DB_ROOT_PASSWORD \
        --connect-timeout=3 --shutdown-timeout=15 shutdown >/dev/null 2>&1
    for _ in $(seq 1 20); do
        port_up "$DB_PORT" || return 0
        sleep 1
    done
    echo "MariaDB не закрылась штатно — снимаю процесс (InnoDB восстановится при следующем старте)"
    pkill -x mariadbd.exe
}

if [ "${1:-}" = "stop" ]; then
    pkill -x python.exe 2>/dev/null
    stop_db
    echo "сервер остановлен"
    exit 0
fi

if ! port_up "$DB_PORT"; then
    for attempt in 1 2; do
        nohup wine "$SRV\\mariadb-10.11.16-winx64\\bin\\mariadbd.exe" \
            --defaults-file="$SRV\\mariadb.ini" \
            --basedir="$SRV\\mariadb-10.11.16-winx64" \
            --datadir="$SRV\\data\\mariadb" \
            --pid-file="$SRV\\state\\mariadb-engine.pid" \
            --log-error="$WROOT\\logs\\mariadb.log" \
            --console > /tmp/mariadb.log 2>&1 &
        wait_port $DB_PORT && break
        echo "MariaDB не поднялась с попытки $attempt — пробую ещё раз"
        pkill -x mariadbd.exe 2>/dev/null
        sleep 3
    done
    port_up "$DB_PORT" || { echo "MariaDB не поднялась, смотри /tmp/mariadb.log"; exit 1; }
    echo "MariaDB: порт $DB_PORT готов"
else
    echo "MariaDB уже на $DB_PORT"
fi

if ! port_up "$HTTP_PORT"; then
    cd "$ROOT/Server/artemis" || exit 1
    nohup wine "$SRV\\python\\python.exe" index.py --config config > /tmp/artemis.log 2>&1 &
    wait_port $HTTP_PORT || { echo "ARTEMiS не поднялся, смотри /tmp/artemis.log"; exit 1; }
    echo "ARTEMiS: порт $HTTP_PORT готов"
else
    echo "ARTEMiS уже на $HTTP_PORT"
fi
ss -ltn | grep -E ":$DB_PORT|:$HTTP_PORT|:9999|:7777"
