#!/bin/bash
# Запуск лончера FGOAC scooby под Wine.
#   ./launcher.sh
# Лончер сам поднимает сервер (кнопка Start server или Play) через наш шим.
# Если он перестал реагировать на мышь — закрой и запусти заново.
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
cd "$ROOT" || exit 1
exec wine './FGOAC scooby.exe'
