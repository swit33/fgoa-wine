#!/bin/bash
# Starts the game directly, without the launcher.
# Screen mode, resolution, input and frame rate come from App/fgo-launcher.json.
#   ./play.sh              start it in the game root taken from the config
#   ./play.sh <install>    pass an explicit game root
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
export FGOA_WINE_DIR="$(cd "$HERE/.." && pwd)"
CONFIG="$HOME/.config/fgoa-wine/config.env"
[ -r "$CONFIG" ] && . "$CONFIG"
: "${FGOA_ROOT:=$(cd "$HERE/../.." && pwd)}"
: "${WINEPREFIX:=$HOME/.local/share/fgoa-wine/prefix}"
export FGOA_ROOT WINEPREFIX
exec python3 "$HERE/launch.py" "${1:-$FGOA_ROOT}" --run
