#!/bin/bash
# Снять наш слой с Wine-префикса: вернуть настоящий pwsh, убрать шим и шрифты.
# Игру, её данные и перевод НЕ трогает.
#   ./uninstall.sh            снять шим и шрифты, конфиг оставить
#   ./uninstall.sh --purge    ещё и удалить ~/.config/fgoa-wine/
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

echo "префикс: $PREFIX"

if [ -f "$SHIM" ] && { file "$SHIM" | grep -q PE32 || grep -q 'fgoa-wine pwsh shim' "$SHIM" 2>/dev/null; }; then
    if [ -f "$PSDIR/pwsh.real.exe" ]; then
        mv -f "$PSDIR/pwsh.real.exe" "$SHIM"
        echo "настоящий PowerShell возвращён на место"
    else
        rm -f "$SHIM"
        echo "шим удалён"
    fi
fi
rm -f "$PSDIR/pwsh-stub.ini"

while IFS='|' read -r name file; do
    case "$name" in ''|'#'*) continue ;; esac
    wine reg delete "$FONTS_REG" /v "$name" /f >/dev/null 2>&1 || true
    rm -f "$PREFIX/drive_c/windows/Fonts/$file"
done < "$HERE/fonts/fonts.list"
echo "наши шрифты убраны из префикса и реестра"

if [ "${1:-}" = "--purge" ]; then
    rm -rf "$(dirname "$CONFIG")"
    echo "удалён $CONFIG"
fi

wineserver -k 2>/dev/null || true
echo "готово (игра и её английский набор не тронуты)"
