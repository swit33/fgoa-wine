#!/usr/bin/env python3
"""Запуск FGO Arcade под Wine без PowerShell.

Читает App/fgo-launcher.json (режим экрана, разрешение, ввод, fps) и:
  * пишет DEVICE\\runtime\\segatools.runtime.ini так, как это делал App\\FGO_Launcher.ps1
    (абсолютные пути, план сети, [gfx]/[amvideo] из конфига, UTF-16);
  * в режиме --print-args выдаёт sh-фрагмент с аргументами и переменными для инжектора;
  * в режиме --run сам запускает игру через inject.exe.

  python3 launch.py <install_root>              # только сгенерировать runtime-ини
  python3 launch.py <install_root> --print-args  # + показать параметры запуска
  python3 launch.py <install_root> --run         # запустить игру (то же делает play.sh)

Корень установки по умолчанию — $FGOA_ROOT (из ~/.config/fgoa-wine/config.env) или папка выше fgoa-wine.
"""
import hashlib
import json
import os
import re
import subprocess
import sys

# план сети для одиночного режима — App/FGO_LocalNetwork.ps1, Get-FgoNetworkPlan(auto)
NET = dict(server="192.168.100.1", subnet="192.168.100.0", addrSuffix=11, routerSuffix=1,
           broadcast="127.0.0.1")
PORTS = dict(http=777, billing=9999, aime=7777)

# конфиг Mesa для шейдеров игры лежит рядом со скриптами, в ../drirc.d
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, os.pardir))
DRIRC_DIR = os.path.join(REPO_DIR, "config", "drirc.d")
DEFAULT_ROOT = (os.environ.get("FGOA_ROOT")
                or os.path.abspath(os.path.join(REPO_DIR, os.pardir)))


def option_value(argv, name):
    """Значение опции вида --name value или --name=value."""
    for i, item in enumerate(argv):
        if item == name and i + 1 < len(argv):
            return argv[i + 1]
        if item.startswith(name + "="):
            return item.split("=", 1)[1]
    return None


def native_render_argument(width, height):
    """Выбор движкового режима — как в FGO_Launcher.ps1."""
    if width * 9 > height * 16:
        return "-wqhd"
    if width * 9 == height * 16:
        if width <= 1280 and height <= 720:
            return "-hdtv720"
        if width < 2560 and height < 1440:
            return "-hdtv1080"
        return "-wqhd"
    return "-wqxga" if width >= 2560 else "-wuxga"


def ensure_active_card(root):
    """Игра берёт карту (аккаунт) из DEVICE/aime.txt. Если файл пуст, она заводит
    «непривязанный» аккаунт 0xFFFFFFFF, на котором лончер потом падает. Если в профиле
    есть аккаунт с валидным id — вписываем его код в карту сами.
    """
    aime = os.path.join(root, "DEVICE", "aime.txt")
    try:
        with open(aime, encoding="utf-8") as fh:
            if fh.read().strip():
                return None
    except OSError:
        pass
    try:
        with open(os.path.join(root, "Server", "state", "fgo-players.json"), encoding="utf-8") as fh:
            players = json.load(fh)
    except (OSError, ValueError):
        return None
    for key, value in players.items():
        if not isinstance(value, dict) or not value.get("access_code"):
            continue
        try:
            aime_id = int(value.get("aime_id") or key.split(":", 1)[1])
        except (ValueError, IndexError):
            continue
        if 0 < aime_id <= 2147483647:
            os.makedirs(os.path.dirname(aime), exist_ok=True)
            with open(aime, "w", encoding="utf-8") as fh:
                fh.write(str(value["access_code"]))
            return aime_id
    return None


def load_config(root):
    with open(os.path.join(root, "App", "fgo-launcher.json"), encoding="utf-8") as fh:
        cfg = json.load(fh)
    mode = cfg.get("displayMode")
    if mode not in ("windowed", "borderless", "exclusive"):
        mode = "windowed" if cfg.get("windowed") else "exclusive"
    return dict(mode=mode,
                width=int(cfg.get("resolutionWidth") or 1280),
                height=int(cfg.get("resolutionHeight") or 720),
                fps=int(cfg.get("targetFps") or 60),
                input=cfg.get("inputMode") if cfg.get("inputMode") in ("xinput", "keyboard") else "xinput",
                monitor_device=cfg.get("monitorDevice") or "")


def set_ini(text, section, key, value):
    """Правит key=... внутри [section]; создаёт секцию/ключ, если их нет."""
    lines = text.split("\r\n")
    header = re.compile(r"^\s*\[([^\]]+)\]")
    cur, sec_start, sec_end = None, None, len(lines)
    for i, line in enumerate(lines):
        m = header.match(line)
        if m:
            if cur == section:
                sec_end = i
                break
            cur = m.group(1).strip().lower()
            if cur == section.lower():
                sec_start = i + 1
    if sec_start is None:
        lines += ["", f"[{section}]", f"{key}={value}"]
        return "\r\n".join(lines)
    pattern = re.compile(r"^(\s*" + re.escape(key) + r"\s*=).*$", re.IGNORECASE)
    for i in range(sec_start, sec_end):
        if pattern.match(lines[i]):
            lines[i] = pattern.sub(lambda m: m.group(1) + str(value), lines[i])
            return "\r\n".join(lines)
    lines.insert(sec_end, f"{key}={value}")
    return "\r\n".join(lines)


def main():
    root = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else DEFAULT_ROOT)
    cfg = load_config(root)
    # режим и разрешение могут прийти аргументами (лончер передаёт их в FGO_Launcher.ps1)
    for flag, key in (("--mode", "mode"), ("--width", "width"), ("--height", "height"),
                      ("--input", "input"), ("--fps", "fps")):
        value = option_value(sys.argv, flag)
        if value:
            cfg[key] = int(value) if key in ("width", "height", "fps") else value
    # путь, каким его видит процесс внутри Wine: Z: == /
    W = "Z:" + root.replace("/", "\\")
    install, game, device = W, W + "\\App", W + "\\DEVICE"
    windowed = cfg["mode"] != "exclusive"
    framed = cfg["mode"] == "windowed"

    updates = {
        "vfs": {"amfs": install + "\\AMFS", "option": game + "\\option",
                "appdata": install + "\\GameData"},
        "aime": {"aimePath": device + "\\aime.txt"},
        "printer": {"mainFwPath": device + "\\printer_main_fw.bin",
                    "paramFwPath": device + "\\printer_param_fw.bin",
                    "dspFwPath": device + "\\printer_dsp_fw.bin",
                    "printerOutPath": device + "\\print\\players\\unassigned"},
        "keychip": {"billingCa": device + "\\ca.crt", "billingPub": device + "\\billing.pub",
                    "subnet": NET["subnet"]},
        "misc": {"nextProcessFilePath": device + "\\NextProcess.txt"},
        "dns": {"default": NET["server"], "startupPort": PORTS["http"],
                "billingPort": PORTS["billing"], "aimedbPort": PORTS["aime"]},
        "netenv": {"enable": 1, "routerSuffix": NET["routerSuffix"],
                   "addrSuffix": NET["addrSuffix"], "broadcast": NET["broadcast"]},
        "gfx": {"windowed": int(windowed), "framed": int(framed),
                "width": cfg["width"], "height": cfg["height"],
                "logicalWidth": cfg["width"], "logicalHeight": cfg["height"],
                "preserveAspect": 1, "monitor": 0, "monitorDevice": cfg["monitor_device"]},
        "amvideo": {"resolutionWidth": cfg["width"], "resolutionHeight": cfg["height"]},
        "io4": {"mode": cfg["input"]},
        "touch": {"remap": 1, "inputWidth": 1920, "inputHeight": 1080, "nativeCoordinates": 0},
        "system": {"freeplay": 0},
        "clock": {"timezone": 0, "daystart": 0, "startHour": 0, "startMinute": 0,
                  "timewarp": 0, "writeable": 0},
    }

    base = os.path.join(root, "App", "segatools.ini")
    target = os.path.join(root, "DEVICE", "runtime", "segatools.runtime.ini")
    with open(base, "rb") as fh:
        text = fh.read().decode("utf-8-sig").replace("\r\n", "\n").replace("\n", "\r\n")
    for section, keys in updates.items():
        for key, value in keys.items():
            text = set_ini(text, section, key, value)
    os.makedirs(os.path.dirname(target), exist_ok=True)
    # [Text.Encoding]::Unicode — UTF-16LE с BOM, иначе нативные хуки портят пути
    with open(target, "w", encoding="utf-16", newline="") as fh:
        fh.write(text)

    card = ensure_active_card(root)
    if card is not None:
        print(f"DEVICE/aime.txt был пуст — вписал карту аккаунта aime_id={card}")

    env = {
        "SEGATOOLS_CONFIG_PATH": "Z:" + target.replace("/", "\\"),
        "FGO_INSTALL_ROOT": install,
        "FGO_TARGET_FPS": str(cfg["fps"]),
        "FGO_LOCAL_NETWORK": "1",
        "FGO_LOCAL_HTTP_PORT": str(PORTS["http"]),
        "FGO_LOCAL_BILLING_PORT": str(PORTS["billing"]),
        "FGO_LOCAL_AIME_PORT": str(PORTS["aime"]),
        "FGO_PRINT_METADATA_ONLY": "1",
        "FGO_ZH_ENABLED": "0",           # английский наложен на файлы, хук zh не нужен
        # имя разделяемой памяти, куда лончер пишет колоду (формула из GameCommunication.cs)
        "FGO_DECK_CHANNEL": "FGODeck_" + hashlib.sha256(
            game.rstrip("\\").upper().encode("utf-8")).hexdigest().upper(),
        "DRIRC_CONFIGDIR": DRIRC_DIR,
    }
    if not os.path.isdir(DRIRC_DIR):
        print(f"предупреждение: нет конфига Mesa {DRIRC_DIR} — шейдеры игры скорее всего не соберутся",
              file=sys.stderr)
    if cfg["mode"] == "borderless":
        env["__COMPAT_LAYER"] = "DISABLEDXMAXIMIZEDWINDOWEDMODE"
        env["FGO_BORDERLESS_COMPOSED"] = "1"

    G = game
    args = ["inject.exe", "-d", "-k", G + "\\fgoglcompat.dll", "-k", G + "\\fgohook.dll",
            G + "\\ago.exe", native_render_argument(cfg["width"], cfg["height"])]
    if windowed:
        args.append("-w")
    args.append("--wasapi-shared")

    if "--print-args" in sys.argv:
        for key, value in env.items():
            print(f"export {key}={sh_quote(value)}")
        print("LAUNCH_ARGS=(" + " ".join(sh_quote(a) for a in args) + ")")
        return 0

    if "--run" not in sys.argv:
        print(f"ini: {target}  ({cfg['mode']} {cfg['width']}x{cfg['height']} "
              f"{native_render_argument(cfg['width'], cfg['height'])})")
        return 0

    os.environ.update(env)
    os.environ.setdefault("WINEPREFIX", os.path.expanduser("~/.local/share/fgoa-wine/prefix"))
    os.environ["WINEDEBUG"] = "-all"
    os.chdir(os.path.join(root, "App"))
    os.execvp("wine", ["wine"] + args)


def sh_quote(value):
    return "'" + str(value).replace("'", "'\\''") + "'"


if __name__ == "__main__":
    sys.exit(main())
