"""Shared shim plumbing: config, paths, Windows<->Linux conversion, logging, subprocesses.

The shim (shim/pwsh.exe) is a bash script sitting where pwsh.exe belongs. Wine runs it as
a host process, so the handlers live in a normal Linux environment: python3, bash, wine.
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


def launch_log_path():
    """Where the game writes its output when we hand it over to the background (Play)."""
    logs = os.path.join(install_root(), "logs")
    os.makedirs(logs, exist_ok=True)
    return os.path.join(logs, "fgo-launch-%s.log" % time.strftime("%Y%m%d-%H%M%S"))


def log(line):
    try:
        with open(log_path(), "a", encoding="utf-8") as fh:
            fh.write(f"[{time.strftime('%F %T')}] {line}\n")
    except OSError:
        pass


def log_call(name, argv):
    log(f"{name}: {' '.join(argv)}" if argv else f"{name}: (no arguments)")


def win_path(host_path):
    """Host path -> the path a process inside Wine sees (Z: == /)."""
    return "Z:" + os.path.abspath(host_path).replace("/", "\\")


def host_path(win):
    """Windows path to a host path. Understands Z: (the Linux root) and any other drive
    (mapped into the prefix drive_c under the matching letter)."""
    win = (win or "").strip().strip('"')
    if len(win) >= 2 and win[1] == ":":
        drive, rest = win[0].upper(), win[2:].replace("\\", "/").lstrip("/")
        if drive == "Z":
            return "/" + rest
        return os.path.join(wineprefix(), "drive_c", rest)
    return win.replace("\\", "/")


def deck_channel():
    """Name of the shared memory the launcher publishes the deck into.
    Exactly as in GameCommunication.ChannelName: sha256 of the full App path in upper
    case (trailing slash trimmed), hex upper case, prefix FGODeck_."""
    app = win_path(app_dir()).rstrip("\\").upper()
    return "FGODeck_" + hashlib.sha256(app.encode("utf-8")).hexdigest().upper()


def run(cmd, cwd=None, env=None, timeout=None, quiet=False):
    """Run with inherited stdio: the launcher reads our output into its log panel."""
    log(f"run: {' '.join(cmd)}" + (f" (cwd={cwd})" if cwd else ""))
    full_env = dict(os.environ)
    # without this the python helpers buffer their output and the launcher's panel stays empty
    full_env.setdefault("PYTHONUNBUFFERED", "1")
    if env:
        full_env.update(env)
    try:
        proc = subprocess.run(cmd, cwd=cwd, env=full_env, timeout=timeout)
        return proc.returncode
    except subprocess.TimeoutExpired:
        if not quiet:
            print(f"[fgoa-shim] the command did not finish within {timeout}s: {' '.join(cmd)}")
        log(f"timeout: {' '.join(cmd)}")
        return 124
    except FileNotFoundError as exc:
        print(f"[fgoa-shim] not found: {exc}")
        log(f"not found: {exc}")
        return 127


def spawn_detached(cmd, log_file, cwd=None, env=None):
    """A background process that outlives the launcher: its own streams, its own session."""
    log(f"spawn detached: {' '.join(cmd)} -> {log_file}")
    full_env = dict(os.environ)
    full_env.setdefault("PYTHONUNBUFFERED", "1")
    if env:
        full_env.update(env)
    handle = open(log_file, "ab")
    subprocess.Popen(cmd, cwd=cwd, env=full_env, stdin=subprocess.DEVNULL,
                     stdout=handle, stderr=handle, start_new_session=True,
                     close_fds=True)


def script(name):
    return os.path.join(SCRIPTS_DIR, name)


def arg_value(argv, name, default=None):
    """Value of a PowerShell-style argument: '-InstallRoot C:\\FGO' -> C:\\FGO."""
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
