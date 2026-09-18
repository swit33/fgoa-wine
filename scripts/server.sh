#!/bin/bash
# The local FGO server (MariaDB + ARTEMiS) under Wine.
#   ./server.sh          bring up whatever is not up yet
#   ./server.sh stop     stop it (MariaDB the graceful way, through mariadb-admin)
# Ports: ALL.Net 777, billing 9999, AimeDB 7777, database 8889 (install.sh moves it off
# 8888 when something else holds that port; override with FGOA_DB_PORT).
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
DB_PORT="${FGOA_DB_PORT:-8889}"
HTTP_PORT="${FGOA_HTTP_PORT:-777}"

wait_port() { for _ in $(seq 1 40); do ss -ltn | grep -q ":$1 " && return 0; sleep 1; done; return 1; }
port_up()   { ss -ltn | grep -q ":$1 "; }

# Close the database the way their Stop-FGOLocalServer.ps1 does: mariadb-admin with the
# root password from their own script and --no-defaults (otherwise [client] in mariadb.ini
# gets in the way).
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
    echo "MariaDB did not shut down gracefully - taking the process down (InnoDB recovers on the next start)"
    pkill -x mariadbd.exe
}

if [ "${1:-}" = "stop" ]; then
    pkill -x python.exe 2>/dev/null
    stop_db
    echo "server stopped"
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
        echo "MariaDB did not come up on attempt $attempt - trying once more"
        pkill -x mariadbd.exe 2>/dev/null
        sleep 3
    done
    port_up "$DB_PORT" || { echo "MariaDB did not come up, see /tmp/mariadb.log"; exit 1; }
    echo "MariaDB: port $DB_PORT is up"
else
    echo "MariaDB is already on $DB_PORT"
fi

if ! port_up "$HTTP_PORT"; then
    cd "$ROOT/Server/artemis" || exit 1
    nohup wine "$SRV\\python\\python.exe" index.py --config config > /tmp/artemis.log 2>&1 &
    wait_port $HTTP_PORT || { echo "ARTEMiS did not come up, see /tmp/artemis.log"; exit 1; }
    echo "ARTEMiS: port $HTTP_PORT is up"
else
    echo "ARTEMiS is already on $HTTP_PORT"
fi
ss -ltn | grep -E ":$DB_PORT|:$HTTP_PORT|:9999|:7777"
