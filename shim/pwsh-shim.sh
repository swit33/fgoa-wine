#!/bin/bash
# Shim in place of PowerShell for the FGOAC scooby launcher under Wine.
#
# The launcher looks for pwsh.exe and starts it through CreateProcess. Wine runs a
# non-PE file when it carries a shebang, so the shim is a bash script and all the logic
# lives in shim/handlers/*.py (plain host programs: python3, bash, wine).
#
# The launcher's contract - nine call sites:
#   -Command '... [IntPtr]::Size ...'                       PowerShell version probe
#   -Command '.... . $env:FGO_CHECK_SCRIPT; Test-FgoWritableLayout ...'   writable-layout check
#   -File FGO_EnvironmentCheck.ps1                          environment report
#   -File Apply-EN-Patch.ps1 [-InstallRoot ..]              apply/roll back English
#   -File Start-FGOLocalServer.ps1 [-ServerHost ..]         start the server
#   -File Stop-FGOLocalServer.ps1                           stop the server
#   -File Stop-FGOLocalServerWhenIdle.ps1 -FrontendProcessId N
#   -File FGO_Launcher.ps1 -DisplayMode .. -ResolutionWidth .. (the Play button)
#   -File Apply-EN-Patch.ps1 (from the updater, with a new payload)
#
# Any other call is logged and fails - we never answer a silent "success".
set -u

SELF_DIR="$(cd "$(dirname "$0")" && pwd)"
CONFIG="${FGOA_SHIM_CONFIG:-$HOME/.config/fgoa-wine/config.env}"
# shellcheck disable=SC1090
[ -r "$CONFIG" ] && . "$CONFIG"
# the handlers live in this folder, not next to the shim inside the prefix
HANDLERS="${FGOA_HANDLERS:-$SELF_DIR/handlers}"
# the launcher runs scripts with <root>/App as cwd - good enough as a fallback path
if [ -z "${FGOA_ROOT:-}" ] && [ "${PWD%[\\/]App}" != "$PWD" ]; then
    FGOA_ROOT="$(cd "$PWD/.." && pwd)"
fi
export FGOA_ROOT

# The PE stub appends --fgoa-done <path> to every call: we write our exit code there,
# because Wine runs bash as a separate unix process, so the launcher cannot tell when
# the work ended (it clears serverConfiguring and drops the server status too early).
DONE_FILE=""
_args=()
while [ $# -gt 0 ]; do
    case "$1" in
        --fgoa-done) DONE_FILE="${2:-}"; shift 2 ;;
        *) _args+=("$1"); shift ;;
    esac
done
[ ${#_args[@]} -gt 0 ] && set -- "${_args[@]}" || set --
if [ -n "$DONE_FILE" ]; then
    _unix=$(winepath -u "$DONE_FILE" 2>/dev/null || true)
    [ -n "$_unix" ] || _unix=$(printf '%s' "$DONE_FILE" | sed 's|^[Zz]:||; s|\\|/|g')
    case "$_unix" in /*) DONE_FILE="$_unix" ;; esac
    trap 'rc=$?; printf "%s" "$rc" > "$DONE_FILE" 2>/dev/null || true' EXIT
fi

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
    # basename is no good here: the path is a Windows one, the separator is Linux's
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
        echo "[fgoa-wine] Unknown shim call: $*"
        echo "[fgoa-wine] The launcher looks updated and calls a new script. Add a handler under shim/handlers/."
    } | tee -a "$LOG" >&2
    exit 1
fi

if [ ! -f "$HANDLERS/$handler.py" ]; then
    {
        echo "[fgoa-wine] No handler at $HANDLERS/$handler.py"
        echo "[fgoa-wine] Check FGOA_HANDLERS in $CONFIG (install.sh writes it)."
    } | tee -a "$LOG" >&2
    exit 1
fi

# -u: handler output reaches the launcher's log panel live instead of at the end.
# It is also copied into logs/server-control.log: that is the file the launcher shows
# in its "Server Did Not Start" dialog (the original ps1 files wrote a transcript there).
CONTROL_LOG="${FGOA_ROOT:-}/logs/server-control.log"
if [ -d "${FGOA_ROOT:-}" ]; then
    mkdir -p "${FGOA_ROOT}/logs" 2>/dev/null || true
    printf '[%s] %s\n' "$(date '+%F %T')" "$*" >> "$CONTROL_LOG" 2>/dev/null || true
    python3 -u "$HANDLERS/$handler.py" "$@" 2>&1 | tee -a "$CONTROL_LOG"
    exit "${PIPESTATUS[0]}"
fi
exec python3 -u "$HANDLERS/$handler.py" "$@"
