#!/bin/bash
# Запуск игры FGO Arcade напрямую, без лончера.
# Режим экрана/разрешение/ввод берутся из App/fgo-launcher.json.
#   ./play.sh              запустить в корне из конфига
#   ./play.sh <install>    явно указать корень установки
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
export FGOA_WINE_DIR="$(cd "$HERE/.." && pwd)"
CONFIG="$HOME/.config/fgoa-wine/config.env"
[ -r "$CONFIG" ] && . "$CONFIG"
: "${FGOA_ROOT:=$(cd "$HERE/../.." && pwd)}"
: "${WINEPREFIX:=$HOME/.local/share/fgoa-wine/prefix}"
export FGOA_ROOT WINEPREFIX
exec python3 "$HERE/launch.py" "${1:-$FGOA_ROOT}" --run
