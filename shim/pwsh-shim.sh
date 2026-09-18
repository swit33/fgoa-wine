#!/bin/bash
# Шим вместо PowerShell для лончера FGOAC scooby под Wine.
#
# Лончер ищет pwsh.exe и запускает его через CreateProcess. Wine умеет запускать
# не-PE файл, если у него есть shebang, — поэтому шим это bash-скрипт, а вся логика
# в shim/handlers/*.py (обычные хостовые программы: python3, bash, wine).
#
# Контракт лончера — девять вызовов:
#   -Command '... [IntPtr]::Size ...'                       проба версии PowerShell
#   -Command '.... . $env:FGO_CHECK_SCRIPT; Test-FgoWritableLayout ...'   проверка записи
#   -File FGO_EnvironmentCheck.ps1                          отчёт об окружении
#   -File Apply-EN-Patch.ps1 [-InstallRoot ..]              накат/откат английского
#   -File Start-FGOLocalServer.ps1 [-ServerHost ..]         старт сервера
#   -File Stop-FGOLocalServer.ps1                           стоп сервера
#   -File Stop-FGOLocalServerWhenIdle.ps1 -FrontendProcessId N
#   -File FGO_Launcher.ps1 -DisplayMode .. -ResolutionWidth .. (кнопка Play)
#   -File Apply-EN-Patch.ps1 (из апдейтера, с новым payload)
#
# Любой другой вызов логируется и возвращает ошибку — тихо «успех» не отвечаем.
set -u

SELF_DIR="$(cd "$(dirname "$0")" && pwd)"
CONFIG="${FGOA_SHIM_CONFIG:-$HOME/.config/fgoa-wine/config.env}"
# shellcheck disable=SC1090
[ -r "$CONFIG" ] && . "$CONFIG"
# хендлеры лежат в репозитории, а не рядом с шимом в префиксе
HANDLERS="${FGOA_HANDLERS:-$SELF_DIR/handlers}"
# лончер запускает скрипты с рабочим каталогом <корень>/App — годится как резервный путь
if [ -z "${FGOA_ROOT:-}" ] && [ "${PWD%[\\/]App}" != "$PWD" ]; then
    FGOA_ROOT="$(cd "$PWD/.." && pwd)"
fi
export FGOA_ROOT

LOG="${FGOA_SHIM_LOG:-/tmp/fgoa-shim.log}"
{
    printf '=== %s cwd=%s argv=%d root=%s\n' "$(date '+%F %T')" "$PWD" "$#" "${FGOA_ROOT:-?}"
    for a in "$@"; do printf '  arg: %s\n' "$a"; done
    env | grep -E '^(FGO_|WINEPREFIX=)' | sed 's/^/  env: /'
} >> "$LOG" 2>&1

mode=""; target=""; command=""
prev=""
for a in "$@"; do
    case "$prev" in
        -File)    mode=file;    target="$a" ;;
        -Command) mode=command; command="$a" ;;
    esac
    prev="$a"
done

handler=""
if [ "$mode" = file ]; then
    # basename здесь не годится: путь Windows-ный, а разделитель в Linux другой
    base="${target##*[\\/]}"
    case "$base" in
        FGO_Launcher.ps1)                 handler=FGO_Launcher ;;
        Start-FGOLocalServer.ps1)         handler=Start-FGOLocalServer ;;
        Stop-FGOLocalServer.ps1)          handler=Stop-FGOLocalServer ;;
        Stop-FGOLocalServerWhenIdle.ps1)  handler=Stop-FGOLocalServerWhenIdle ;;
        Apply-EN-Patch.ps1)               handler=Apply-EN-Patch ;;
        FGO_EnvironmentCheck.ps1)         handler=FGO_EnvironmentCheck ;;
        FGO_StartupChecks.ps1)            handler=FGO_StartupChecks ;;
    esac
elif [ "$mode" = command ]; then
    case "$command" in
        *'IntPtr'*'Size'*)            handler=probe ;;
        *Test-FgoWritableLayout*)     handler=FGO_StartupChecks ;;
    esac
else
    case "${1:-}" in
        -v|--version) echo "fgoa-wine pwsh shim 1.0"; exit 0 ;;
    esac
fi

if [ -z "$handler" ]; then
    {
        echo "[fgoa-wine] Неизвестный вызов шима: $*"
        echo "[fgoa-wine] Похоже, лончер обновился и зовёт новый скрипт. Добавь хендлер в shim/handlers/."
    } | tee -a "$LOG" >&2
    exit 1
fi

if [ ! -f "$HANDLERS/$handler.py" ]; then
    {
        echo "[fgoa-wine] Нет хендлера $HANDLERS/$handler.py"
        echo "[fgoa-wine] Проверь FGOA_HANDLERS в $CONFIG (его пишет install.sh)."
    } | tee -a "$LOG" >&2
    exit 1
fi

# -u: вывод хендлеров идёт вживую в панель логов лончера, а не в конце
exec python3 -u "$HANDLERS/$handler.py" "$@"
