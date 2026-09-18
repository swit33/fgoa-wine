#!/bin/bash
# fgoa-wine — ставит наш слой на уже собранную папку игры FGO Arcade.
#
# Вход: папка игры, собранная снаружи (本体 Cloud23333 + 前端 1.02 + релиз лончера
# FGOAC scooby). Признаки, которые скрипт проверяет: App/ago.exe, App/FGO_Runtime.dll
# (он появляется с 前端 1.01), Server/tools/, payload/ + manifest.json и FGOAC scooby.exe.
# Откуда игра взялась и в каких архивах лежала, скрипт не знает и знать не хочет.
#
# Что делает (идемпотентно):
#   1) проверяет, что это та самая папка, и перечисляет, чего не хватает;
#   2) наш слой: импорт-патч ago.exe, перевод (патч хука fgozh.dll, 1683 файла,
#      строки в ago.exe), правки серверных инструментов;
#   3) готовит Wine-префикс: создаёт при необходимости, ставит шим вместо pwsh.exe,
#      ставит и регистрирует шрифты WPF, пишет конфиг шима;
#   4) конфиг Mesa для шейдеров игры (config/drirc.d);
#   5) порты: ALL.Net 777 привилегированный (--sysctl), БД уходит с занятого 8888;
#   6) проверяет результат и печатает, что делать дальше.
#
# Запуск (релиз лежит в папке игры, как <root>/fgoa-wine):
#   ./install.sh                       # корень по умолчанию — папка выше fgoa-wine
#   ./install.sh --root /path/to/game  # явный корень
#   ./install.sh --verify              # только проверить уже установленное
#   ./install.sh --sysctl              # дополнительно разрешить порт 777 (нужен root)
#   ./install.sh --no-fonts | --no-shim | --prefix /path/to/prefix
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
        -h|--help)   sed -n '2,25p' "$0"; exit 0 ;;
        *) echo "неизвестный ключ: $1" >&2; exit 2 ;;
    esac
done

mkdir -p "$TMPDIR_FGOA"
exec > >(tee -a "$LOG") 2>&1

say()  { printf '%s\n' "$*"; }
step() { printf '\n=== %s\n' "$*"; }
warn() { printf '! %s\n' "$*" >&2; }
die()  { printf 'ОШИБКА: %s\n' "$*" >&2; exit 1; }
need() { command -v "$1" >/dev/null 2>&1 || die "нужна команда '$1' (установи пакет)"; }

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

# ---------------------------------------------------------------- что на входе
# Обязательные файлы. Последние два — метки того, что папка собрана до конца:
# App/FGO_Runtime.dll приходит с 前端 1.01, payload/ и manifest.json — с релизом лончера.
REQUIRED_FILES=(
    'App/ago.exe' 'App/am/amdaemon.exe' 'App/fgohook.dll' 'App/inject.exe'
    'App/config.json' 'App/segatools.ini' 'App/FGO_Runtime.dll'
    'AMFS/ICF1' 'AMFS/ICF2'
    'Server/python/python.exe' 'Server/mariadb.ini'
    'Server/mariadb-10.11.16-winx64/bin/mariadbd.exe' 'Server/artemis/config/core.yaml'
    'Server/tools/fgo_account.py'
    'FGOAC scooby.exe' 'manifest.json' 'payload/App/zh/text-outputs.json'
)
# Что означает каждый из «меточных» файлов, если его нет.
LAYOUT_HINTS=(
    'App/FGO_Runtime.dll|на папку не накатан 前端 1.01/1.02'
    'FGOAC scooby.exe|не распакован релиз лончера FGOAC scooby'
    'manifest.json|не распакован релиз лончера FGOAC scooby'
    'payload/App/zh/text-outputs.json|не распакован релиз лончера FGOAC scooby'
)

check_game_layout() {
    local missing=() f hint
    for f in "${REQUIRED_FILES[@]}"; do
        [ -e "$ROOT/$f" ] || missing+=("$f")
    done
    if [ ${#missing[@]} -eq 0 ]; then
        say "папка игры на месте: $(basename "$ROOT") ($(find "$ROOT/App" -maxdepth 1 -type f | wc -l) файлов в App)"
        return 0
    fi
    say "это не готовая папка игры — не хватает:"
    for f in "${missing[@]}"; do
        hint=""
        for h in "${LAYOUT_HINTS[@]}"; do
            [ "${h%%|*}" = "$f" ] && hint=" — ${h#*|}"
        done
        printf '  %s%s\n' "$f" "$hint"
    done
    printf '\nОжидается папка, где уже лежат: 本体 Cloud23333, поверх него 前端 1.02, поверх —\nрелиз лончера FGOAC scooby (zip распакован в эту же папку). Распаковкой скрипт не занимается:\nсобери такую папку снаружи и запусти установку заново.\n'
    return 1
}

# ---------------------------------------------------------------- наш слой
apply_our_layer() {
    local pristine="$ROOT/App/ago.exe.pristine"
    [ -f "$pristine" ] || cp -f "$ROOT/App/ago.exe" "$pristine"
    cp -f "$pristine" "$ROOT/App/ago.exe"          # всегда собираем из чистого файла
    cp -f "$pristine" "$ROOT/App/ago.exe.orig"     # бэкап, который ждёт patch-ago-import.py
    python3 "$HERE/scripts/patch-ago-import.py" "$ROOT/App/ago.exe" SetWindowFeedbackSetting IsWindow --apply >/dev/null
    say "импорт SetWindowFeedbackSetting -> IsWindow: применён"
    python3 "$HERE/scripts/apply-en.py" "$ROOT" --apply | tail -3
    python3 "$HERE/scripts/patch-server.py" "$ROOT" --apply | tail -2
}

# ---------------------------------------------------------------- префикс
setup_prefix() {
    if [ ! -d "$PREFIX/drive_c" ]; then
        say "создаю Wine-префикс $PREFIX"
        mkdir -p "$PREFIX"
        WINEARCH=win64 wine_run wineboot -u >/dev/null 2>&1 || die "wineboot не смог создать префикс"
        wine_run wineserver -w
    else
        say "префикс уже есть: $PREFIX"
    fi

    if [ "$DO_SHIM" = 1 ]; then
        local stub="$HERE/shim/stub/pwsh-stub.exe"
        # пересобираю, если исходник новее (иначе в префикс уедет устаревший PE: он не ждёт
        # шим, лончер видит мгновенный выход и сбрасывает статус сервера)
        if [ ! -f "$stub" ] || [ "$HERE/shim/stub/pwsh-stub.c" -nt "$stub" ]; then
            say "собираю PE-стаб"
            "$HERE/shim/stub/build.sh" "Z:$HERE/shim/pwsh-shim.sh" >/dev/null || die "стаб не собрался"
        fi
        mkdir -p "$PREFIX/drive_c/Program Files/PowerShell/7"
        local shim="$PREFIX/drive_c/Program Files/PowerShell/7/pwsh.exe"
        if [ -f "$shim" ] && ! file "$shim" | grep -q PE32 && ! grep -q 'fgoa-wine pwsh shim' "$shim" 2>/dev/null; then
            mv "$shim" "$PREFIX/drive_c/Program Files/PowerShell/7/pwsh.real.exe"
            say "настоящий PowerShell сохранён как pwsh.real.exe"
        fi
        cp -f "$stub" "$shim"; chmod 755 "$shim"
        printf 'shim=Z:%s\n' "$HERE/shim/pwsh-shim.sh" > "$PREFIX/drive_c/Program Files/PowerShell/7/pwsh-stub.ini"
        say "шим установлен вместо pwsh.exe (PE-стаб + bash-шим)"
    fi

    if [ "$DO_FONTS" = 1 ]; then
        cp -f "$HERE"/fonts/*.ttf "$PREFIX/drive_c/windows/Fonts/"
        while IFS='|' read -r name file; do
            case "$name" in ''|'#'*) continue ;; esac
            wine_run reg add "$FONTS_REG" /v "$name" /t REG_SZ /d "$file" /f >/dev/null
        done < "$HERE/fonts/fonts.list"
        say "шрифты WPF установлены и зарегистрированы (без регистрации лончер падает)"
        wine_run wineserver -k >/dev/null 2>&1 || true
        sleep 2
    fi

    # Выпадающие списки лончера под Wine рисуются чёрными прямоугольниками: попап
    # ComboBox объявлен AllowsTransparency="True", Wine укладывает его в layered-окно
    # и теряет альфу. Софтверный рендеринг WPF эту дорожку обходит (проверено).
    wine_run reg add 'HKCU\Software\Microsoft\Avalon.Graphics' /v DisableHWAcceleration \
        /t REG_DWORD /d 1 /f >/dev/null 2>&1 \
        && say "WPF переведён на софтверный рендеринг (иначе выпадающие списки чёрные)"

    mkdir -p "$CONFIG_DIR"
    cat > "$CONFIG" <<EOF
# Конфиг fgoa-wine: читается шимом и хендлерами.
FGOA_ROOT="$ROOT"
WINEPREFIX="$PREFIX"
FGOA_SCRIPTS="$HERE/scripts"
FGOA_HANDLERS="$HERE/shim/handlers"
FGOA_SHIM_LOG="/tmp/fgoa-shim.log"
EOF
    say "конфиг шима: $CONFIG"
}

# ---------------------------------------------------------------- порты и drirc
setup_ports() {
    if [ "$(sysctl -n net.ipv4.ip_unprivileged_port_start 2>/dev/null || echo 1024)" -gt 777 ]; then
        if [ "$DO_SYSCTL" = 1 ]; then
            say "разрешаю непривилегированные порты с 777 (sudo)"
            sudo sysctl -w net.ipv4.ip_unprivileged_port_start=777
            printf '# FGO Arcade: серверу ALL.Net нужен порт 777.\nnet.ipv4.ip_unprivileged_port_start = 777\n' \
                | sudo tee /etc/sysctl.d/99-fgoa-ports.conf >/dev/null
        else
            warn "порт 777 привилегированный, а sysctl не поднят: сервер ALL.Net не забиндится."
            warn "Разово:  sudo sysctl -w net.ipv4.ip_unprivileged_port_start=777"
            warn "Навсегда: echo 'net.ipv4.ip_unprivileged_port_start = 777' | sudo tee /etc/sysctl.d/99-fgoa-ports.conf"
            warn "или перезапусти install.sh с --sysctl"
        fi
    else
        say "порт 777 доступен непривилегированным процессам"
    fi

    local dbport
    if port_busy "$DB_DEFAULT_PORT"; then
        dbport=$(free_port 8889)
        warn "порт $DB_DEFAULT_PORT занят (на этой машине — докер); БД перевожу на $dbport"
    else
        dbport="$DB_DEFAULT_PORT"
    fi
    FGOA_WIN_ROOT="Z:$ROOT" wine_run "$ROOT/Server/python/python.exe" \
        "$HERE/scripts/set-ports.py" 777 "$dbport" >/dev/null 2>&1 \
        || warn "не удалось перевести порты автоматически (сделай это на странице Advanced в лончере)"
}

setup_drirc() {
    local dir="$HERE/config/drirc.d"
    mkdir -p "$dir"
    local f
    for f in /usr/share/drirc.d/*.conf; do
        ln -sf "$f" "$dir/$(basename "$f")" 2>/dev/null || true
    done
    [ -f "$dir/99-fgoa.conf" ] || die "нет config/drirc.d/99-fgoa.conf в релизе"
    say "конфиг Mesa для шейдеров игры: $dir"
}

# ---------------------------------------------------------------- проверка
verify_all() {
    local fails=0 f
    step "проверка"
    for f in 'App/ago.exe' 'App/fgohook.dll' 'AMFS/ICF1' 'Server/python/python.exe' \
             'Server/mariadb.ini' 'FGOAC scooby.exe' 'App/zh/en-patch.json' 'App/ago.exe.pristine'; do
        if [ -e "$ROOT/$f" ]; then say "[OK]   $f"; else say "[FAIL] нет $ROOT/$f"; fails=$((fails+1)); fi
    done
    if python3 "$HERE/scripts/apply-en.py" "$ROOT" --verify >/dev/null 2>&1; then
        say "[OK]   перевод на месте (хук zh + набор на диске)"
    else
        say "[FAIL] перевод не сходится — запусти install.sh заново"; fails=$((fails+1))
    fi
    if python3 "$HERE/scripts/patch-server.py" "$ROOT" --verify >/dev/null 2>&1; then
        say "[OK]   серверные правки на месте (bad_output, Max All Servants)"
    else
        say "[FAIL] серверные правки не наложены — запусти install.sh заново"; fails=$((fails+1))
    fi
    if [ -f "$PREFIX/drive_c/Program Files/PowerShell/7/pwsh-stub.ini" ]; then
        say "[OK]   шим: $(cat "$PREFIX/drive_c/Program Files/PowerShell/7/pwsh-stub.ini")"
    else
        say "[FAIL] шим не установлен в $PREFIX"; fails=$((fails+1))
    fi
    if wine_run reg query "$FONTS_REG" 2>/dev/null | grep -q 'Segoe UI (TrueType)'; then
        say "[OK]   шрифты зарегистрированы в реестре префикса"
    else
        say "[FAIL] шрифты не зарегистрированы (лончер упадёт на FailFast)"; fails=$((fails+1))
    fi
    if wine_run reg query 'HKCU\Software\Microsoft\Avalon.Graphics' /v DisableHWAcceleration 2>/dev/null | grep -q '0x1'; then
        say "[OK]   выпадающие списки лончера (софтверный рендеринг WPF)"
    else
        say "[FAIL] WPF рисует с аппаратным ускорением — выпадающие списки будут чёрными"; fails=$((fails+1))
    fi
    if [ -r "$CONFIG" ]; then say "[OK]   конфиг шима: $CONFIG"; else say "[FAIL] нет $CONFIG"; fails=$((fails+1)); fi
    printf '\n'
    if [ "$fails" -eq 0 ]; then say "ИТОГ: всё на месте."; else say "ИТОГ: проблем — $fails."; fi
    return "$fails"
}

# ---------------------------------------------------------------- main
say "fgoa-wine — установка FGO Arcade под Wine"
say "корень игры : $ROOT"
say "префикс     : $PREFIX"
say "лог         : $LOG"

if [ "$DO_VERIFY" = 1 ]; then
    check_game_layout || exit 3
    verify_all || true
    exit $?
fi

need wine; need python3

step "проверка папки игры"
check_game_layout || die "собери папку игры (本体 + 前端 1.02 + релиз лончера) и запусти установку заново"

step "наш слой: патч ago.exe, перевод, серверные правки"; apply_our_layer
step "Wine-префикс"; setup_prefix
step "Mesa drirc"; setup_drirc
step "порты"; setup_ports

verify_all || true
cat <<EOF

Дальше:
  1) Запусти лончер:  $HERE/scripts/launcher.sh
  2) ВАЖНО: до первого запуска игры создай аккаунт — в лончере страница Account → New Account
     (иначе игра сама заведёт «непривязанный» аккаунт 0xFFFFFFFF, на котором лончер сыпет ошибками).
  3) Собери колоду: Cards and Deck → двойным щелчком до 30 карт (колода отдаётся игре при Play).
  4) Play. Первый запуск идёт около минуты (компиляция шейдеров). Игра стартует в фоне,
     а лончер остаётся живым; живой вывод игры — в logs/fgo-launch-<дата>.log.
     Если на экране старта SYSTEM STARTUP (SATELLITE:SUB) и Location Server: WAIT,
     а потом ERROR 8404 — игра считает себя под-кабинетом, лечится в её тест-меню:
     F1 (F2 двигает стрелку, F1 подтверждает) -> Game Settings -> Startup Mode ->
     Main Unit -> Exit, затем Play заново.
  5) Если лончер перестал реагировать на мышь — закрой и запусти заново.
EOF
