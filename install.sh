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
#   2) this layer: the two ago.exe patches (the SetWindowFeedbackSetting import, the
#      robust-access request), the English dataset (the fgozh.dll hook patch, 1683 files, the
#      strings inside ago.exe), the server-side fixes;
#   3) prepares the Wine prefix: creates it when needed, installs the shim in place of
#      pwsh.exe, installs and registers the WPF fonts, writes the shim config;
#   4) the Mesa config the game's shaders need (config/drirc.d);
#   5) checks the two things that need root (port 777, the cabinet addresses on lo) and tells you
#      to run ./install-sudo.sh, which is the only script here that asks for a password; also picks
#      a free database port and tells the scripts about it;
#   6) verifies the result and prints what to do next.
#
# Usage (the release sits inside the game folder as <root>/fgoa-wine):
#   ./install.sh                       # game root defaults to the folder above fgoa-wine
#   ./install.sh --root /path/to/game  # explicit game root
#   ./install.sh --prefix /path        # Wine prefix (default ~/.local/share/fgoa-wine/prefix)
#   ./install.sh --verify              # check an existing install, change nothing
#   sudo ./install-sudo.sh             # the root-only steps: port 777 and the cabinet addresses
#   ./install.sh --use-wayland         # run Wine on its Wayland driver instead of X11. X11 is
#                                      # the default: through XWayland the launcher and the game
#                                      # take input on the better-trodden path (docs/INTERNALS.md)
#   ./install.sh --no-fonts | --no-shim
set -u

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="${FGOA_ROOT:-$(cd "$HERE/.." && pwd)}"
PREFIX="${FGOA_PREFIX:-$HOME/.local/share/fgoa-wine/prefix}"
CONFIG_DIR="$HOME/.config/fgoa-wine"
CONFIG="$CONFIG_DIR/config.env"
TMPDIR_FGOA="${TMPDIR:-/tmp}/fgoa-wine-install"
LOG="$TMPDIR_FGOA/install.log"

DO_VERIFY=0; DO_FONTS=1; DO_SHIM=1
# X11 by default: Wine picks its Wayland driver whenever WAYLAND_DISPLAY is set, and the
# X11/XWayland path is the one this launcher behaves on (see docs/INTERNALS.md).
BACKEND=x11

while [ $# -gt 0 ]; do
    case "$1" in
        --root)      ROOT="$2"; shift 2 ;;
        --prefix)    PREFIX="$2"; shift 2 ;;
        --verify)    DO_VERIFY=1; DO_FONTS=0; DO_SHIM=0; shift ;;
        --use-x11)   BACKEND=x11; shift ;;
        --use-wayland) BACKEND=wayland; shift ;;
        --no-fonts)  DO_FONTS=0; shift ;;
        --no-shim)   DO_SHIM=0; shift ;;
        # the root-only steps moved out: nothing in this file needs a password any more
        --sysctl|--no-cabinet-net)
                     echo "$1 moved out of install.sh - the root-only steps live in their own script:" >&2
                     echo "  sudo ./install-sudo.sh" >&2; exit 2 ;;
        -h|--help)   awk 'NR>1 && /^set -u/{exit} NR>1{print}' "$0"; exit 0 ;;
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
# The fonts are prepared from the system, so fontconfig has to be there to find them.
need_fonts_tools() {
    need fc-match
    need python3
}

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
    # Wine's EGL backend refuses the robust-access context the game asks for (it is what
    # breaks ago.exe on NVIDIA); dropping the request lets the context exist at all.
    if python3 "$HERE/scripts/patch-ago-gl.py" "$ROOT/App/ago.exe" --apply >/dev/null; then
        say "robust-access context flag: dropped"
    else
        warn "could not drop the robust-access flag - is this the expected ago.exe?"
    fi
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
        # The fonts are deliberately not shipped with this project: the installer takes a free font
        # from the system, rewrites its internal family name (the launcher's WPF front end asks for
        # families no Linux system has) and registers the result in the prefix. See fonts/NOTICE.md.
        local dest="$PREFIX/drive_c/windows/Fonts"
        local fonts_failed=0
        mkdir -p "$dest"
        while IFS='|' read -r name file pattern family; do
            case "$name" in ''|'#'*) continue ;; esac
            local src
            src=$(fc-match -f '%{file}' "$pattern" 2>/dev/null || true)
            if [ -z "$src" ] || [ ! -f "$src" ]; then
                warn "no free font matches '$pattern' for family '$family'"
                fonts_failed=$((fonts_failed + 1))
                continue
            fi
            if python3 "$HERE/fonts/rename_font.py" "$src" "$dest/$file" "$family" >/dev/null; then
                wine_run reg add "$FONTS_REG" /v "$name" /t REG_SZ /d "$file" /f >/dev/null
            else
                warn "could not prepare $file from $src"
                fonts_failed=$((fonts_failed + 1))
            fi
        done < "$HERE/fonts/fonts.list"
        if [ "$fonts_failed" -gt 0 ]; then
            warn "$fonts_failed font(s) missing: install Liberation Sans/Mono and DejaVu Sans Mono"
            warn "  Arch/CachyOS: sudo pacman -S ttf-liberation ttf-dejavu"
            warn "  Debian/Ubuntu: sudo apt install fonts-liberation fonts-dejavu-core"
            warn "the launcher will not start without them (it needs the families it asks for)"
        else
            say "WPF fonts prepared from the system and registered in the prefix"
        fi
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
# x11 (default) or wayland: which driver Wine uses for the launcher and the game.
FGOA_WINE_BACKEND="$BACKEND"
EOF
    say "shim config: $CONFIG (Wine backend: $BACKEND)"
}

# ---------------------------------------------------------------- checks for the root-only steps
# Nothing in this file needs root. The cabinet network and the privileged port are set up by
# install-sudo.sh; here they are only looked at, so that a plain install tells you to run it.
#
# The cabinet network is 192.168.100.0/24 because the platform expects it (App/FGO_LocalNetwork.ps1:
# Server = 192.168.100.1, Cabinet = 192.168.100.11). A cabinet that cannot reach the location server
# at 192.168.100.1 comes up as a sub unit, which the game answers with ERROR 8404.
cabinet_addresses_missing() {
    ip -4 addr show lo 2>/dev/null | grep -q '192\.168\.100\.1/' || return 0
    ip -4 addr show lo 2>/dev/null | grep -q '192\.168\.100\.11/' || return 0
    return 1
}

check_privileged() {
    local need_sudo=0
    if [ "$(sysctl -n net.ipv4.ip_unprivileged_port_start 2>/dev/null || echo 1024)" -gt 777 ]; then
        warn "port 777 is privileged and not allowed for unprivileged processes yet"
        need_sudo=1
    else
        say "port 777 is available to unprivileged processes"
    fi
    if cabinet_addresses_missing; then
        warn "the cabinet network addresses are not on lo (the game may come up as a sub cabinet)"
        need_sudo=1
    else
        say "cabinet network addresses are on lo"
    fi
    if [ "$need_sudo" = 1 ]; then
        say "run the root-only steps yourself, they are in their own script:"
        say "  sudo $HERE/install-sudo.sh"
    fi
}

# ---------------------------------------------------------------- ports and drirc
setup_ports() {
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

    # server.sh reads the database port from here: mariadb.ini (which set-ports.py just wrote) and
    # this file have to agree, or MariaDB comes up on one port while the script waits on another.
    if [ -f "$CONFIG" ]; then
        if grep -q '^FGOA_DB_PORT=' "$CONFIG" 2>/dev/null; then
            sed -i "s|^FGOA_DB_PORT=.*|FGOA_DB_PORT=\"$dbport\"|" "$CONFIG"
        else
            printf 'FGOA_DB_PORT="%s"\n' "$dbport" >> "$CONFIG"
        fi
    fi
    say "database port $dbport (written into the platform's config and into config.env)"
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
    if python3 "$HERE/scripts/patch-ago-gl.py" "$ROOT/App/ago.exe" --verify >/dev/null 2>&1; then
        say "[OK]   ago.exe: robust-access context flag dropped"
    else
        say "[FAIL] ago.exe still asks for a robust-access context — run install.sh again"; fails=$((fails+1))
    fi
    if grep -q '^FGOA_WINE_BACKEND="wayland"' "$CONFIG" 2>/dev/null; then
        say "[OK]   Wine backend: wayland"
    elif grep -q '^FGOA_WINE_BACKEND=' "$CONFIG" 2>/dev/null; then
        say "[OK]   Wine backend: x11"
    else
        say "[OK]   Wine backend: x11 (nothing in the config says otherwise)"
    fi
    if ip -4 addr show lo 2>/dev/null | grep -q '192\.168\.100\.1/'; then
        say "[OK]   cabinet network address on lo (the game will find a location server)"
    else
        say "[WARN] no cabinet address on lo — the game may come up as a sub cabinet (ERROR 8404); sudo $HERE/install-sudo.sh"
    fi
    if [ "$(sysctl -n net.ipv4.ip_unprivileged_port_start 2>/dev/null || echo 1024)" -le 777 ]; then
        say "[OK]   port 777 is available to unprivileged processes"
    else
        say "[WARN] port 777 is still privileged — the ALL.Net server cannot bind; sudo $HERE/install-sudo.sh"
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
    if [ -f "$PREFIX/drive_c/windows/Fonts/SegoeUI.ttf" ] && [ -f "$PREFIX/drive_c/windows/Fonts/CascadiaMono.ttf" ]; then
        say "[OK]   font files prepared in the prefix (renamed free fonts)"
    else
        say "[FAIL] font files are missing from $PREFIX/drive_c/windows/Fonts"; fails=$((fails+1))
    fi
    if wine_run reg query 'HKCU\Software\Microsoft\Avalon.Graphics' /v DisableHWAcceleration 2>/dev/null | grep -q '0x1'; then
        say "[OK]   launcher dropdowns (WPF software rendering)"
    else
        say "[FAIL] WPF still uses hardware acceleration — dropdowns will be black"; fails=$((fails+1))
    fi
    if [ -r "$CONFIG" ]; then say "[OK]   shim config: $CONFIG"; else say "[FAIL] $CONFIG is missing"; fails=$((fails+1)); fi
    local ini_db config_db
    ini_db=$(sed -n 's/^port=\([0-9]*\)[[:space:]]*$/\1/p' "$ROOT/Server/mariadb.ini" 2>/dev/null | head -1)
    config_db=$(sed -n 's/^FGOA_DB_PORT="\([0-9]*\)"$/\1/p' "$CONFIG" 2>/dev/null | head -1)
    if [ -n "$ini_db" ] && [ "$ini_db" = "$config_db" ]; then
        say "[OK]   database port $ini_db (the platform and server.sh agree)"
    elif [ -z "$config_db" ]; then
        say "[WARN] config.env has no FGOA_DB_PORT — server.sh assumes 8889 while the platform uses ${ini_db:-?}; run install.sh again"
    else
        say "[FAIL] database port mismatch: the platform uses $ini_db, server.sh would use $config_db"; fails=$((fails+1))
    fi
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
if [ "$DO_FONTS" = 1 ]; then need_fonts_tools; fi

step "checking the game folder"
check_game_layout || die "assemble the game folder (本体 + 前端 1.02 + the launcher release) and run the installer again"

step "this layer: ago.exe patches, English dataset, server-side fixes"; apply_our_layer
step "Wine prefix"; setup_prefix
step "Mesa drirc"; setup_drirc
step "root-only steps (checked here, run by install-sudo.sh)"; check_privileged
step "ports and database"; setup_ports

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
     Steps that need root (port 777, the cabinet addresses) are not done by this script: run
     sudo $HERE/install-sudo.sh once, and ./install.sh --verify will report both.
     If the startup screen reads SYSTEM STARTUP (SATELLITE:SUB) with Location Server: WAIT
     and the game then dies with ERROR 8404, it thinks it is a sub cabinet. The installer puts
     the cabinet network addresses on lo to stop that, but when it still happens the cure is the
     game's own test menu: F1 (F2 moves the arrow, F1 confirms) -> Game Settings ->
     Startup Mode -> Main Unit -> Exit, then press Play again.
  4) If the launcher stops reacting to the mouse, close it and start it again.
EOF
