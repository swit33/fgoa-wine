#!/bin/bash
# Сборка PE-стаба. winegcc --target=x86_64-windows использует заголовки и импортные
# библиотеки Wine (mingw не нужен), на выходе — настоящий PE.
set -eu
HERE="$(cd "$(dirname "$0")" && pwd)"
SHIM_PATH="${1:-Z:$(cd "$HERE/.." && pwd)/pwsh-shim.sh}"
OUT="$HERE/pwsh-stub.exe"
winegcc --target=x86_64-windows -O2 -Wall -D"FGOA_SHIM_SCRIPT=\"$SHIM_PATH\"" -o "$OUT" "$HERE/pwsh-stub.c"
file "$OUT" | cut -c1-90
