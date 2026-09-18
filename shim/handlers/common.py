"""Общая часть шима: конфиг, пути, конверсия Windows↔Linux, лог, запуск процессов.

Шим (shim/pwsh.exe) — bash-скрипт на месте pwsh.exe. Wine запускает его как хостовый
процесс, поэтому хендлеры живут в обычной Linux-среде: python3, bash, wine — всё доступно.
"""
import hashlib
import os
import subprocess
import sys
import time

CONFIG_PATH = os.environ.get("FGOA_SHIM_CONFIG", os.path.expanduser("~/.config/fgoa-wine/config.env"))
HANDLERS_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_DIR = os.path.dirname(os.path.dirname(HANDLERS_DIR))     # fgoa-wine/
SCRIPTS_DIR = os.path.join(REPO_DIR, "scripts")


def load_config():
    conf = {}
    if os.path.isfile(CONFIG_PATH):
        with open(CONFIG_PATH, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                conf[key.strip()] = value.strip().strip('"').strip("'")
    return conf


CONF = load_config()


def install_root():
    return (os.environ.get("FGOA_ROOT") or CONF.get("FGOA_ROOT")
            or os.path.abspath(os.path.join(REPO_DIR, os.pardir)))


def wineprefix():
    return os.environ.get("WINEPREFIX") or CONF.get("WINEPREFIX") or os.path.expanduser("~/.fgoa-test")


def app_dir():
    return os.path.join(install_root(), "App")


def server_dir():
    return os.path.join(install_root(), "Server")


def log_path():
    return os.environ.get("FGOA_SHIM_LOG", CONF.get("FGOA_SHIM_LOG", "/tmp/fgoa-shim.log"))


def log(line):
    try:
        with open(log_path(), "a", encoding="utf-8") as fh:
            fh.write(f"[{time.strftime('%F %T')}] {line}\n")
    except OSError:
        pass


def log_call(name, argv):
    log(f"{name}: {' '.join(argv)}" if argv else f"{name}: (без аргументов)")


def win_path(host_path):
    """Хостовый путь -> путь, каким его видит процесс внутри Wine (Z: == /)."""
    return "Z:" + os.path.abspath(host_path).replace("/", "\\")


def host_path(win):
    """Путь из Windows-вида в хостовый. Понимает Z: (корень Linux) и любой другой диск
    (мапится в drive_c соответствующей буквой префикса)."""
    win = (win or "").strip().strip('"')
    if len(win) >= 2 and win[1] == ":":
        drive, rest = win[0].upper(), win[2:].replace("\\", "/").lstrip("/")
        if drive == "Z":
            return "/" + rest
        return os.path.join(wineprefix(), "drive_c", rest)
    return win.replace("\\", "/")


def deck_channel():
    """Имя разделяемой памяти, куда лончер кладёт колоду.
    Точно как в GameCommunication.ChannelName: sha256 от полного пути App в верхнем
    регистре (хвостовой слеш срезан), hex в верхнем регистре, префикс FGODeck_."""
    app = win_path(app_dir()).rstrip("\\").upper()
    return "FGODeck_" + hashlib.sha256(app.encode("utf-8")).hexdigest().upper()


def run(cmd, cwd=None, env=None, timeout=None, quiet=False):
    """Запуск с наследованием stdio: лончер читает наш вывод в свою панель логов."""
    log(f"run: {' '.join(cmd)}" + (f" (cwd={cwd})" if cwd else ""))
    full_env = dict(os.environ)
    if env:
        full_env.update(env)
    try:
        proc = subprocess.run(cmd, cwd=cwd, env=full_env, timeout=timeout)
        return proc.returncode
    except subprocess.TimeoutExpired:
        if not quiet:
            print(f"[fgoa-shim] команда не завершилась за {timeout} с: {' '.join(cmd)}")
        log(f"timeout: {' '.join(cmd)}")
        return 124
    except FileNotFoundError as exc:
        print(f"[fgoa-shim] не найдено: {exc}")
        log(f"not found: {exc}")
        return 127


def spawn_detached(cmd, log_file, cwd=None, env=None):
    """Фоновый процесс, который переживёт лончер: свои потоки — в файл, новая сессия."""
    log(f"spawn detached: {' '.join(cmd)} -> {log_file}")
    full_env = dict(os.environ)
    if env:
        full_env.update(env)
    handle = open(log_file, "ab")
    subprocess.Popen(cmd, cwd=cwd, env=full_env, stdin=subprocess.DEVNULL,
                     stdout=handle, stderr=handle, start_new_session=True,
                     close_fds=True)


def script(name):
    return os.path.join(SCRIPTS_DIR, name)


def arg_value(argv, name, default=None):
    """Значение аргумента PowerShell-вида: '-InstallRoot C:\\FGO' -> C:\\FGO."""
    for i, item in enumerate(argv):
        if item == name and i + 1 < len(argv):
            return argv[i + 1]
        if item.startswith(name + ":"):
            return item.split(":", 1)[1]
    return default


def has_flag(argv, name):
    return any(item == name or item.startswith(name + ":") for item in argv)


def port_open(port, host="127.0.0.1", timeout=0.4):
    import socket
    with socket.socket() as sock:
        sock.settimeout(timeout)
        return sock.connect_ex((host, port)) == 0
