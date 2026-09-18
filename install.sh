#!/bin/bash
# fgoa-wine — applies this layer to an already assembled FGO Arcade game folder.
#
# Input: a game folder put together elsewhere (Cloud23333's 本体 + 前端 1.02 on top of
# it + the FGOAC scooby launcher release). What the script checks for: App/ago.exe,
# App/FGO_Runtime.dll (it arrives with 前端 1.01), Server/tools/, payload/ +
# manifest.json and FGOAC scooby.exe. Where the game came from and in which archives it
# travelled is not its business.
#
# What it does (idempotent):
#   1) checks that this is that folder and lists whatever is missing;
#   2) this layer: the ago.exe import patch, the English dataset (the fgozh.dll hook
#      patch, 1683 files, the strings inside ago.exe), the server-side fixes;
#   3) prepares the Wine prefix: creates it when needed, installs the shim in place of
#      pwsh.exe, installs and registers the WPF fonts, writes the shim config;
#   4) the Mesa config the game's shaders need (config/drirc.d);
#   5) the ports: ALL.Net 777 is privileged (--sysctl), the database moves off a busy 8888;
#   6) verifies the result and prints what to do next.
#
# Usage (the release sits inside the game folder as <root>/fgoa-wine):
#   ./install.sh                       # game root defaults to the folder above fgoa-wine
#   ./install.sh --root /path/to/game  # explicit game root
#   ./install.sh --prefix /path        # Wine prefix (default ~/.local/share/fgoa-wine/prefix)
#   ./install.sh --verify              # check an existing install, change nothing
#   ./install.sh --sysctl              # also allow port 777 (needs root)
#   ./install.sh --no-fonts | --no-shim
set -u

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="${FGOA_ROOT:-$(cd "$HERE/.." && pwd)}"
PREFIX="${FGOA_PREFIX:-$HOME/.local/share/fgoa-wine/prefix}"
CONFIG_DIR="$HOME/.config/fgoa-wine"
CONFIG="$CONFIG_DIR/config.env"
TMPDIR_FGOA="${TMPDIR:-/tmp}/fgoa-wine-install"
LOG="$TMPDIR_FGOA/install.log"

DO_VERIFY=0; DO_SYSCTL=0; DO_FONTS=1; DO_SHIM=1

while [ $# -gt 0 ]; do
    case "$1" in
        --root)      ROOT="$2"; shift 2 ;;
        --prefix)    PREFIX="$2"; shift 2 ;;
        --verify)    DO_VERIFY=1; DO_FONTS=0; DO_SHIM=0; shift ;;
        --sysctl)    DO_SYSCTL=1; shift ;;
        --no-fonts)  DO_FONTS=0; shift ;;
        --no-shim)   DO_SHIM=0; shift ;;
        -h|--help)   sed -n '2,24p' "$0"; exit 0 ;;
        *) echo "unknown option: $1" >&2; exit 2 ;;
    esac
done

mkdir -p "$TMPDIR_FGOA"
exec > >(tee -a "$LOG") 2>&1

say()  { printf '%s\n' "$*"; }
step() { printf '\n=== %s\n' "$*"; }
warn() { printf '! %s\n' "$*" >&2; }
die()  { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
need() { command -v "$1" >/dev/null 2>&1 || die "the '$1' command is required (install its package)"; }

export WINEPREFIX="$PREFIX"
export WINEDEBUG="${WINEDEBUG:--all}"
FONTS_REG='HKLM\Software\Microsoft\Windows NT\CurrentVersion\Fonts'
DB_DEFAULT_PORT=8888

wine_run() { WINEPREFIX="$PREFIX" WINEDEBUG="${WINEDEBUG}" wine "$@"; }
port_busy() { ss -ltn 2>/dev/null | grep -q ":$1 "; }
free_port() {
    local p=$1
    while port_busy "$p"; do p=$((p + 1)); done
    echo "$p"
}

# ---------------------------------------------------------------- input
# Required files. The last four are the markers that the folder was assembled all the way:
# App/FGO_Runtime.dll comes with 前端 1.01, payload/ and manifest.json with the launcher release.
REQUIRED_FILES=(
    'App/ago.exe' 'App/am/amdaemon.exe' 'App/fgohook.dll' 'App/inject.exe'
    'App/config.json' 'App/segatools.ini' 'App/FGO_Runtime.dll'
    'AMFS/ICF1' 'AMFS/ICF2'
    'Server/python/python.exe' 'Server/mariadb.ini'
    'Server/mariadb-10.11.16-winx64/bin/mariadbd.exe' 'Server/artemis/config/core.yaml'
    'Server/tools/fgo_account.py'
    'FGOAC scooby.exe' 'manifest.json' 'payload/App/zh/text-outputs.json'
)
# What each marker file means when it is missing.
LAYOUT_HINTS=(
    'App/FGO_Runtime.dll|this folder has not had 前端 1.01/1.02 applied'
    'FGOAC scooby.exe|the FGOAC scooby launcher release was not unpacked here'
    'manifest.json|the FGOAC scooby launcher release was not unpacked here'
    'payload/App/zh/text-outputs.json|the FGOAC scooby launcher release was not unpacked here'
)

check_game_layout() {
    local missing=() f hint
    for f in "${REQUIRED_FILES[@]}"; do
        [ -e "$ROOT/$f" ] || missing+=("$f")
    done
    if [ ${#missing[@]} -eq 0 ]; then
        say "game folder looks right: $(basename "$ROOT") ($(find "$ROOT/App" -maxdepth 1 -type f | wc -l) files in App)"
        return 0
    fi
    say "this is not an assembled game folder — missing:"
    for f in "${missing[@]}"; do
        hint=""
        for h in "${LAYOUT_HINTS[@]}"; do
            [ "${h%%|*}" = "$f" ] && hint=" — ${h#*|}"
        done
        printf '  %s%s\n' "$f" "$hint"
    done
    printf '\nExpected: a folder that already holds Cloud23333'"'"'s 本体, his 前端 1.02 on top of it,\nand the FGOAC scooby launcher release unpacked over that (the zip goes into the same\nfolder). This script does not unpack anything: assemble such a folder first and run the\ninstaller again.\n'
    return 1
}

# ---------------------------------------------------------------- this layer
apply_our_layer() {
    local pristine="$ROOT/App/ago.exe.pristine"
    [ -f "$pristine" ] || cp -f "$ROOT/App/ago.exe" "$pristine"
    cp -f "$pristine" "$ROOT/App/ago.exe"          # always rebuild from the pristine file
    cp -f "$pristine" "$ROOT/App/ago.exe.orig"     # backup patch-ago-import.py expects
    python3 "$HERE/scripts/patch-ago-import.py" "$ROOT/App/ago.exe" SetWindowFeedbackSetting IsWindow --apply >/dev/null
    say "import SetWindowFeedbackSetting -> IsWindow: applied"
    python3 "$HERE/scripts/apply-en.py" "$ROOT" --apply | tail -3
    python3 "$HERE/scripts/patch-server.py" "$ROOT" --apply | tail -2
}

# ---------------------------------------------------------------- prefix
setup_prefix() {
    if [ ! -d "$PREFIX/drive_c" ]; then
        say "creating the Wine prefix $PREFIX"
        mkdir -p "$PREFIX"
        WINEARCH=win64 wine_run wineboot -u >/dev/null 2>&1 || die "wineboot could not create the prefix"
        wine_run wineserver -w
    else
        say "prefix already exists: $PREFIX"
    fi

    if [ "$DO_SHIM" = 1 ]; then
        local stub="$HERE/shim/stub/pwsh-stub.exe"
        # rebuild when the source is newer: a stale PE would not wait for the shim, the
        # launcher sees an instant exit and drops the server status back to "ports down"
        if [ ! -f "$stub" ] || [ "$HERE/shim/stub/pwsh-stub.c" -nt "$stub" ]; then
            say "building the PE stub"
            "$HERE/shim/stub/build.sh" "Z:$HERE/shim/pwsh-shim.sh" >/dev/null || die "the stub did not build"
        fi
        mkdir -p "$PREFIX/drive_c/Program Files/PowerShell/7"
        local shim="$PREFIX/drive_c/Program Files/PowerShell/7/pwsh.exe"
        if [ -f "$shim" ] && ! file "$shim" | grep -q PE32 && ! grep -q 'fgoa-wine pwsh shim' "$shim" 2>/dev/null; then
            mv "$shim" "$PREFIX/drive_c/Program Files/PowerShell/7/pwsh.real.exe"
            say "the real PowerShell was kept as pwsh.real.exe"
        fi
        cp -f "$stub" "$shim"; chmod 755 "$shim"
        printf 'shim=Z:%s\n' "$HERE/shim/pwsh-shim.sh" > "$PREFIX/drive_c/Program Files/PowerShell/7/pwsh-stub.ini"
        say "shim installed in place of pwsh.exe (PE stub + bash dispatcher)"
    fi

    if [ "$DO_FONTS" = 1 ]; then
        cp -f "$HERE"/fonts/*.ttf "$PREFIX/drive_c/windows/Fonts/"
        while IFS='|' read -r name file; do
            case "$name" in ''|'#'*) continue ;; esac
            wine_run reg add "$FONTS_REG" /v "$name" /t REG_SZ /d "$file" /f >/dev/null
        done < "$HERE/fonts/fonts.list"
        say "WPF fonts installed and registered (without the registry entries the launcher dies)"
        wine_run wineserver -k >/dev/null 2>&1 || true
        sleep 2
    fi

    # The launcher's dropdowns render as black rectangles under Wine: the ComboBox popup is
    # declared AllowsTransparency="True", Wine puts it in a layered window and loses the
    # alpha. WPF's software rendering path avoids that (verified).
    wine_run reg add 'HKCU\Software\Microsoft\Avalon.Graphics' /v DisableHWAcceleration \
        /t REG_DWORD /d 1 /f >/dev/null 2>&1 \
        && say "WPF switched to software rendering (otherwise dropdowns stay black)"

    mkdir -p "$CONFIG_DIR"
    cat > "$CONFIG" <<EOF
# fgoa-wine config: read by the shim, the handlers and the scripts in scripts/.
FGOA_ROOT="$ROOT"
WINEPREFIX="$PREFIX"
FGOA_SCRIPTS="$HERE/scripts"
FGOA_HANDLERS="$HERE/shim/handlers"
FGOA_SHIM_LOG="/tmp/fgoa-shim.log"
EOF
    say "shim config: $CONFIG"
}

# ---------------------------------------------------------------- ports and drirc
setup_ports() {
    if [ "$(sysctl -n net.ipv4.ip_unprivileged_port_start 2>/dev/null || echo 1024)" -gt 777 ]; then
        if [ "$DO_SYSCTL" = 1 ]; then
            say "allowing unprivileged ports from 777 (sudo)"
            sudo sysctl -w net.ipv4.ip_unprivileged_port_start=777
            printf '# FGO Arcade: the ALL.Net server needs port 777.\nnet.ipv4.ip_unprivileged_port_start = 777\n' \
                | sudo tee /etc/sysctl.d/99-fgoa-ports.conf >/dev/null
        else
            warn "port 777 is privileged and the sysctl is not raised: the ALL.Net server cannot bind."
            warn "For now:  sudo sysctl -w net.ipv4.ip_unprivileged_port_start=777"
            warn "For good: echo 'net.ipv4.ip_unprivileged_port_start = 777' | sudo tee /etc/sysctl.d/99-fgoa-ports.conf"
            warn "or run install.sh again with --sysctl"
        fi
    else
        say "port 777 is available to unprivileged processes"
    fi

    local dbport
    if port_busy "$DB_DEFAULT_PORT"; then
        dbport=$(free_port 8889)
        warn "port $DB_DEFAULT_PORT is taken (docker holds it on this machine); moving the database to $dbport"
    else
        dbport="$DB_DEFAULT_PORT"
    fi
    FGOA_WIN_ROOT="Z:$ROOT" wine_run "$ROOT/Server/python/python.exe" \
        "$HERE/scripts/set-ports.py" 777 "$dbport" >/dev/null 2>&1 \
        || warn "could not move the ports automatically (do it on the launcher's Advanced page)"
}

setup_drirc() {
    local dir="$HERE/config/drirc.d"
    mkdir -p "$dir"
    local f
    for f in /usr/share/drirc.d/*.conf; do
        ln -sf "$f" "$dir/$(basename "$f")" 2>/dev/null || true
    done
    [ -f "$dir/99-fgoa.conf" ] || die "config/drirc.d/99-fgoa.conf is missing from the release"
    say "Mesa config for the game's shaders: $dir"
}

# ---------------------------------------------------------------- verification
verify_all() {
    local fails=0 f
    step "verification"
    for f in 'App/ago.exe' 'App/fgohook.dll' 'AMFS/ICF1' 'Server/python/python.exe' \
             'Server/mariadb.ini' 'FGOAC scooby.exe' 'App/zh/en-patch.json' 'App/ago.exe.pristine'; do
        if [ -e "$ROOT/$f" ]; then say "[OK]   $f"; else say "[FAIL] missing $ROOT/$f"; fails=$((fails+1)); fi
    done
    if python3 "$HERE/scripts/apply-en.py" "$ROOT" --verify >/dev/null 2>&1; then
        say "[OK]   English dataset in place (zh hook + files on disk)"
    else
        say "[FAIL] the English dataset does not verify — run install.sh again"; fails=$((fails+1))
    fi
    if python3 "$HERE/scripts/patch-server.py" "$ROOT" --verify >/dev/null 2>&1; then
        say "[OK]   server-side fixes in place (bad_output, Max All Servants)"
    else
        say "[FAIL] the server-side fixes are not applied — run install.sh again"; fails=$((fails+1))
    fi
    if [ -f "$PREFIX/drive_c/Program Files/PowerShell/7/pwsh-stub.ini" ]; then
        say "[OK]   shim: $(cat "$PREFIX/drive_c/Program Files/PowerShell/7/pwsh-stub.ini")"
    else
        say "[FAIL] the shim is not installed in $PREFIX"; fails=$((fails+1))
    fi
    if wine_run reg query "$FONTS_REG" 2>/dev/null | grep -q 'Segoe UI (TrueType)'; then
        say "[OK]   fonts registered in the prefix registry"
    else
        say "[FAIL] fonts are not registered (the launcher will die in FailFast)"; fails=$((fails+1))
    fi
    if wine_run reg query 'HKCU\Software\Microsoft\Avalon.Graphics' /v DisableHWAcceleration 2>/dev/null | grep -q '0x1'; then
        say "[OK]   launcher dropdowns (WPF software rendering)"
    else
        say "[FAIL] WPF still uses hardware acceleration — dropdowns will be black"; fails=$((fails+1))
    fi
    if [ -r "$CONFIG" ]; then say "[OK]   shim config: $CONFIG"; else say "[FAIL] $CONFIG is missing"; fails=$((fails+1)); fi
    printf '\n'
    if [ "$fails" -eq 0 ]; then say "RESULT: everything is in place."; else say "RESULT: $fails problem(s)."; fi
    return "$fails"
}

# ---------------------------------------------------------------- main
say "fgoa-wine — FGO Arcade under Wine"
say "game root : $ROOT"
say "prefix    : $PREFIX"
say "log       : $LOG"

if [ "$DO_VERIFY" = 1 ]; then
    check_game_layout || exit 3
    verify_all || true
    exit $?
fi

need wine; need python3

step "checking the game folder"
check_game_layout || die "assemble the game folder (本体 + 前端 1.02 + the launcher release) and run the installer again"

step "this layer: ago.exe patch, English dataset, server-side fixes"; apply_our_layer
step "Wine prefix"; setup_prefix
step "Mesa drirc"; setup_drirc
step "ports"; setup_ports

verify_all || true
cat <<EOF

Next:
  1) Start the launcher:  $HERE/scripts/launcher.sh
     Its first run sets itself up and creates a starter account called "Master" for you,
     so there is nothing to prepare by hand. Further accounts: the Account page.
  2) Build a deck: Cards and Deck -> double-click up to 30 cards (the deck is handed to the
     game on every Play). As shipped the deck holds one card, so only Mash appears.
  3) Play. The first launch takes about a minute (shader compilation). The game starts in
     the background and the launcher stays responsive; the game's live output goes to
     logs/fgo-launch-<date>.log.
     If the startup screen reads SYSTEM STARTUP (SATELLITE:SUB) with Location Server: WAIT
     and the game then dies with ERROR 8404, it thinks it is a sub cabinet. Fix it in its own
     test menu: F1 (F2 moves the arrow, F1 confirms) -> Game Settings -> Startup Mode ->
     Main Unit -> Exit, then press Play again.
  4) If the launcher stops reacting to the mouse, close it and start it again.
EOF
