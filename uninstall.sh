#!/bin/bash
# Removes this layer from the Wine prefix: puts the real PowerShell back and takes the
# shim and the fonts out. The game, its data and the English dataset are left alone.
#   ./uninstall.sh            remove the shim and the fonts, keep the config
#   ./uninstall.sh --purge    also delete ~/.config/fgoa-wine/
set -eu
HERE="$(cd "$(dirname "$0")" && pwd)"
CONFIG="$HOME/.config/fgoa-wine/config.env"

PREFIX="${WINEPREFIX:-}"
if [ -z "$PREFIX" ] && [ -r "$CONFIG" ]; then
    PREFIX=$(. "$CONFIG"; echo "${WINEPREFIX:-}")
fi
PREFIX="${PREFIX:-$HOME/.local/share/fgoa-wine/prefix}"

FONTS_REG='HKLM\Software\Microsoft\Windows NT\CurrentVersion\Fonts'
export WINEPREFIX="$PREFIX" WINEDEBUG="${WINEDEBUG:--all}"
PSDIR="$PREFIX/drive_c/Program Files/PowerShell/7"
SHIM="$PSDIR/pwsh.exe"

echo "prefix: $PREFIX"

if [ -f "$SHIM" ] && { file "$SHIM" | grep -q PE32 || grep -q 'fgoa-wine pwsh shim' "$SHIM" 2>/dev/null; }; then
    if [ -f "$PSDIR/pwsh.real.exe" ]; then
        mv -f "$PSDIR/pwsh.real.exe" "$SHIM"
        echo "the real PowerShell is back in place"
    else
        rm -f "$SHIM"
        echo "shim removed"
    fi
fi
rm -f "$PSDIR/pwsh-stub.ini"

while IFS='|' read -r name file; do
    case "$name" in ''|'#'*) continue ;; esac
    wine reg delete "$FONTS_REG" /v "$name" /f >/dev/null 2>&1 || true
    rm -f "$PREFIX/drive_c/windows/Fonts/$file"
done < "$HERE/fonts/fonts.list"
echo "our fonts are out of the prefix and its registry"

if [ "${1:-}" = "--purge" ]; then
    rm -rf "$(dirname "$CONFIG")"
    echo "removed $CONFIG"
fi

wineserver -k 2>/dev/null || true
echo "done (the game and its English dataset were not touched)"
