#!/bin/bash
# fgoa-wine — установка FGO Arcade (Cloud23333 local platform) под Wine на Linux.
#
# Что делает (по шагам, всё идемпотентно):
#   1) находит архивы-исходники (本体 Cloud23333, 前端 1.01 и 1.02, релиз лончера FGOAC scooby);
#   2) распаковывает本体, кладёт его в корень установки, попутно исправляя имена частей,
#      которые Google Drive переименовал (part1-003.rar -> part1.rar);
#   3) накатывает 前端 1.01, затем 1.02, затем релиз лончера;
#   4) применяет наш слой: импорт-патч ago.exe, перевод (1683 файла + строки в ago.exe);
#   5) готовит Wine-префикс: создаёт его при необходимости, ставит шим вместо pwsh.exe,
#      ставит и регистрирует шрифты WPF, пишет конфиг шима;
#   6) проверяет порты (ALL.Net 777 привилегированный; БД 8888, если занят — подбирает другой);
#   7) прогоняет проверку и печатает, что делать дальше.
#
# Запуск (релиз лежит в папке установки, как <root>/fgoa-wine):
#   ./install.sh                       # корень по умолчанию — папка выше fgoa-wine
#   ./install.sh --root /path/to/game  # явный корень
#   ./install.sh --verify              # только проверить уже установленное
#   ./install.sh --sysctl              # дополнительно разрешить порт 777 (нужен root)
#   ./install.sh --sources /path/dir   # где искать архивы (можно несколько раз)
#   ./install.sh --force               # перераспаковать本体 поверх существующего
#   ./install.sh --skip-extract        # только слой/префикс, архивы не трогать
set -u

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="${FGOA_ROOT:-$(cd "$HERE/.." && pwd)}"
PREFIX="${FGOA_PREFIX:-$HOME/.local/share/fgoa-wine/prefix}"
CONFIG_DIR="$HOME/.config/fgoa-wine"
CONFIG="$CONFIG_DIR/config.env"
TMPDIR_FGOA="${TMPDIR:-/tmp}/fgoa-wine-install"
LOG="$TMPDIR_FGOA/install.log"

DO_VERIFY=0; DO_SYSCTL=0; DO_FORCE=0; DO_EXTRACT=1; DO_FONTS=1; DO_SHIM=1
SOURCES=()

while [ $# -gt 0 ]; do
    case "$1" in
        --root)      ROOT="$2"; shift 2 ;;
        --prefix)    PREFIX="$2"; shift 2 ;;
        --sources)   SOURCES+=("$2"); shift 2 ;;
        --verify)    DO_VERIFY=1; DO_EXTRACT=0; DO_FONTS=0; DO_SHIM=0; shift ;;
        --sysctl)    DO_SYSCTL=1; shift ;;
        --force)     DO_FORCE=1; shift ;;
        --skip-extract) DO_EXTRACT=0; shift ;;
        --no-fonts)  DO_FONTS=0; shift ;;
        --no-shim)   DO_SHIM=0; shift ;;
        -h|--help)   sed -n '2,26p' "$0"; exit 0 ;;
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
PSWIN='C:\Program Files\PowerShell\7'
FONTS_REG='HKLM\Software\Microsoft\Windows NT\CurrentVersion\Fonts'
DB_DEFAULT_PORT=8888

wine_run() { WINEPREFIX="$PREFIX" WINEDEBUG="${WINEDEBUG}" wine "$@"; }
port_busy() { ss -ltn 2>/dev/null | grep -q ":$1 "; }
free_port() {
    local p=$1
    while port_busy "$p"; do p=$((p + 1)); done
    echo "$p"
}

# ---------------------------------------------------------------- исходники
search_dirs() {
    local d
    for d in "${SOURCES[@]:-}" "$HERE" "$ROOT" "$(dirname "$ROOT")" "$HOME/Downloads" "$PWD"; do
        [ -n "$d" ] && [ -d "$d" ] && echo "$d"
    done
}

find_in_sources() {   # find_in_sources <glob> ... -> первый найденный путь
    local pat d f
    for pat in "$@"; do
        for d in $(search_dirs); do
            f=$(find "$d" -maxdepth 2 -iname "$pat" -not -path '*/_parts-normalized/*' 2>/dev/null | head -1)
            [ -n "$f" ] && { echo "$f"; return 0; }
        done
    done
    return 1
}

# Части本体: Google Drive мог переименовать их в partN-00X.rar -> собираем канонические имена
normalize_parts() {
    local dir="$TMPDIR_FGOA/parts"
    rm -rf "$dir"; mkdir -p "$dir"
    local n src
    for n in 1 2 3 4 5; do
        src=$(find_in_sources "FGOA_Cloud23333.part${n}.rar" "FGOA_Cloud23333.part${n}-*.rar" || true)
        if [ -n "$src" ]; then
            ln -sf "$src" "$dir/FGOA_Cloud23333.part${n}.rar" 2>/dev/null || cp -f "$src" "$dir/FGOA_Cloud23333.part${n}.rar"
        fi
    done
    if [ ! -e "$dir/FGOA_Cloud23333.part5.rar" ]; then
        local zip; zip=$(find_in_sources 'V1.00*.zip' || true)
        if [ -n "$zip" ]; then
            say "part5 беру из $(basename "$zip")"
            unzip -o -j "$zip" 'V1.00/FGOA_Cloud23333.part5.rar' -d "$dir" >/dev/null || warn "не удалось достать part5 из zip"
        fi
    fi
    [ -e "$dir/FGOA_Cloud23333.part1.rar" ] || die "не нашла части本体 (FGOA_Cloud23333.part1..5.rar). Укажи --sources <папка с архивами>"
    echo "$dir"
}

# ---------------------------------------------------------------- распаковка
extract_base() {
    local parts; parts=$(normalize_parts)
    local sizes; sizes=$(du -cbL --apparent-size "$parts"/*.rar | tail -1 | cut -f1)
    say "本体: $(ls "$parts" | wc -l) часть(ей), $((sizes / 1024 / 1024 / 1024)) ГБ — распаковка займёт несколько минут"
    mkdir -p "$ROOT"
    ( cd "$parts" && unrar x -o+ -p"$RAR_PASSWORD" -idq FGOA_Cloud23333.part1.rar "$ROOT/" ) \
        || die "unrar не смог распаковать本体 (пароль/целостность?)"
}

extract_frontend() {
    local version="$1" glob="$2"
    local zip; zip=$(find_in_sources "$glob" || true)
    [ -n "$zip" ] || { warn "не нашла архив 前端 $version — пропускаю"; return 0; }
    local dir="$TMPDIR_FGOA/fe$version"
    rm -rf "$dir"; mkdir -p "$dir"
    unzip -oq "$zip" -d "$dir" || die "не распаковался $zip"
    local rar; rar=$(find "$dir" -name '*part1.rar' | head -1)
    [ -n "$rar" ] || die "внутри $zip нет частей 前端"
    say "前端 $version: распаковываю из $(basename "$zip")"
    ( cd "$(dirname "$rar")" && unrar x -o+ -p"$RAR_PASSWORD" -idq "$(basename "$rar")" "$ROOT/" ) \
        || die "unrar не смог распаковать 前端 $version"
}

extract_launcher() {
    local zip; zip=$(find_in_sources 'FGOAC-scooby-v*.zip' || true)
    [ -n "$zip" ] || die "не нашла релиз лончера (FGOAC-scooby-v*.zip)"
    say "лончер: распаковываю $(basename "$zip")"
    unzip -oq "$zip" -d "$ROOT" || die "не распаковался $zip"
}

check_required_files() {
    local missing=() f
    for f in 'App/ago.exe' 'App/am/amdaemon.exe' 'App/fgohook.dll' 'App/FGO_Runtime.dll' \
             'App/inject.exe' 'App/config.json' 'App/segatools.ini' 'AMFS/ICF1' 'AMFS/ICF2' \
             'DEVICE/runtime/segatools.runtime.ini' 'Server/python/python.exe' 'Server/mariadb.ini' \
             'Server/mariadb-10.11.16-winx64/bin/mariadbd.exe' 'Server/artemis/config/core.yaml' \
             'Server/tools/fgo_account.py' 'FGOAC scooby.exe'; do
        [ -e "$ROOT/$f" ] || missing+=("$f")
    done
    if [ ${#missing[@]} -gt 0 ]; then
        say "не хватает файлов:"
        printf '  %s\n' "${missing[@]}"
        return 1
    fi
    say "обязательные файлы на месте"
    return 0
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
        [ -f "$stub" ] || { say "собираю PE-стаб"; "$HERE/shim/stub/build.sh" "Z:$HERE/shim/pwsh-shim.sh" >/dev/null || die "стаб не собрался"; }
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
    for f in 'App/ago.exe' 'App/fgohook.dll' 'AMFS/ICF1' 'DEVICE/runtime/segatools.runtime.ini' \
             'Server/python/python.exe' 'Server/mariadb.ini' 'FGOAC scooby.exe' \
             'App/zh/en-patch.json' 'App/ago.exe.pristine'; do
        if [ -e "$ROOT/$f" ]; then say "[OK]   $f"; else say "[FAIL] нет $ROOT/$f"; fails=$((fails+1)); fi
    done
    if python3 "$HERE/scripts/apply-en.py" "$ROOT" --verify >/dev/null 2>&1; then
        say "[OK]   перевод совпадает с манифестом"
    else
        say "[FAIL] перевод не сходится — запусти install.sh заново"; fails=$((fails+1))
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

if [ "$DO_VERIFY" = 1 ]; then verify_all; exit $?; fi

need wine; need python3; need unzip
if [ "$DO_EXTRACT" = 1 ]; then need unrar; fi

if [ "$DO_EXTRACT" = 1 ] && { [ "$DO_FORCE" = 1 ] || [ ! -f "$ROOT/App/ago.exe" ]; }; then
    RAR_PASSWORD="${RAR_PASSWORD:-bilibili Cloud23333}"
    step "распаковка本体"; extract_base
    step "前端 1.01";     extract_frontend 1.01 'V1.01*.zip'
    step "前端 1.02";     extract_frontend 1.02 'V1.02*.zip'
    step "релиз лончера"; extract_launcher
else
    step "распаковка"; say "пропускаю (игра уже есть; --force чтобы перераспаковать)"
fi

step "проверка файлов установки"; check_required_files || die "установка неполная — проверь исходники"
step "наш слой: патч ago.exe и перевод"; apply_our_layer
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
  4) Play. Первый запуск идёт около минуты (компиляция шейдеров).
  5) Если лончер перестал реагировать на мышь — закрой и запусти заново.
EOF
