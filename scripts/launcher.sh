#!/bin/bash
# Starts the FGOAC scooby launcher under Wine.
#   ./launcher.sh
# The launcher brings the local server up itself (Start server, or Play) through our shim.
# If it stops reacting to the mouse, close it and start it again.
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
# Wine takes its Wayland driver whenever WAYLAND_DISPLAY is set. This launcher behaves better on
# X11/XWayland (input and window handling - see docs/INTERNALS.md), so that is the default; the
# installer's --use-wayland writes FGOA_WINE_BACKEND=wayland into the config instead.
case "${FGOA_WINE_BACKEND:-x11}" in
    wayland) : ;;
    *)       unset WAYLAND_DISPLAY ;;
esac
cd "$ROOT" || exit 1
exec wine './FGOAC scooby.exe'
