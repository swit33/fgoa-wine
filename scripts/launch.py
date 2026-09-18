#!/usr/bin/env python3
"""Starts FGO Arcade under Wine without PowerShell.

Reads App/fgo-launcher.json (screen mode, resolution, input, fps) and:
  * writes DEVICE\\runtime\\segatools.runtime.ini the way App\\FGO_Launcher.ps1 did
    (absolute paths, network plan, [gfx]/[amvideo] from the config, UTF-16);
  * with --print-args prints an sh fragment with the injector's arguments and variables;
  * with --run starts the game itself through inject.exe.

  python3 launch.py <install_root>               # only generate the runtime INI
  python3 launch.py <install_root> --print-args  # + show the launch parameters
  python3 launch.py <install_root> --run         # start the game (play.sh does the same)

The install root defaults to $FGOA_ROOT (from ~/.config/fgoa-wine/config.env) or the folder above fgoa-wine.
"""
import hashlib
import json
import os
import re
import subprocess
import sys

# network plan for standalone mode - App/FGO_LocalNetwork.ps1, Get-FgoNetworkPlan(auto)
NET = dict(server="192.168.100.1", subnet="192.168.100.0", addrSuffix=11, routerSuffix=1,
           broadcast="127.0.0.1")
PORTS = dict(http=777, billing=9999, aime=7777)

# the Mesa config for the game's shaders sits next to the scripts, in ../config/drirc.d
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, os.pardir))
DRIRC_DIR = os.path.join(REPO_DIR, "config", "drirc.d")
DEFAULT_ROOT = (os.environ.get("FGOA_ROOT")
                or os.path.abspath(os.path.join(REPO_DIR, os.pardir)))


def option_value(argv, name):
    """Value of an option shaped --name value or --name=value."""
    for i, item in enumerate(argv):
        if item == name and i + 1 < len(argv):
            return argv[i + 1]
        if item.startswith(name + "="):
            return item.split("=", 1)[1]
    return None


def native_render_argument(width, height):
    """Picks the engine render mode - same as FGO_Launcher.ps1."""
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
    """The game takes its card (account) from DEVICE/aime.txt. An empty file makes it create
    the "unbound" account 0xFFFFFFFF, which the launcher then chokes on. When the profile
    already holds an account with a valid id, we write its code into the card ourselves.
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
    # Cabinet role: FGO_Launcher.ps1 takes it from fgo-launcher.json and passes it as -sm.
    # "saved" (the default) means pass nothing and let the game use its own saved mode. When
    # that mode is Satellite (Sub Unit) the client waits for the main cabinet's Location
    # Server and shows ERROR 8404 - setting "server" (Main Unit) cures that.
    cabinet = cfg.get("cabinetMode")
    if cabinet not in ("server", "satellite"):
        cabinet = "saved"
    return dict(mode=mode,
                cabinet=cabinet,
                width=int(cfg.get("resolutionWidth") or 1280),
                height=int(cfg.get("resolutionHeight") or 720),
                fps=int(cfg.get("targetFps") or 60),
                input=cfg.get("inputMode") if cfg.get("inputMode") in ("xinput", "keyboard") else "xinput",
                monitor_device=cfg.get("monitorDevice") or "")


def set_ini(text, section, key, value):
    """Edits key=... inside [section], creating the section or key when missing."""
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
    # mode and resolution may arrive as arguments (the launcher passes them to FGO_Launcher.ps1)
    for flag, key in (("--mode", "mode"), ("--width", "width"), ("--height", "height"),
                      ("--input", "input"), ("--fps", "fps")):
        value = option_value(sys.argv, flag)
        if value:
            cfg[key] = int(value) if key in ("width", "height", "fps") else value
    # the path a process inside Wine sees: Z: == /
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
    # [Text.Encoding]::Unicode - UTF-16LE with BOM, or the native hooks mangle the paths
    with open(target, "w", encoding="utf-16", newline="") as fh:
        fh.write(text)

    card = ensure_active_card(root)
    if card is not None:
        print(f"DEVICE/aime.txt was empty - wrote the account card for aime_id={card}")

    # The zh hook loads under Wine only after the patch applied by apply-en.py (5 bytes in
    # fgozh.dll: ntdll does not export NtQueryInformationByName, and without the patch DllMain
    # returns FALSE). With the patch the hook translates the game as the author intended.
    zh_path = os.path.join(root, "App", "zh", "fgozh.dll")
    zh_hook = False
    if os.path.isfile(zh_path):
        with open(zh_path, "rb") as fh:
            zh_hook = fh.read()[0x19E99:0x19E9E] == bytes.fromhex("31c0909090")
        if not zh_hook:
            print("warning: fgozh.dll is not patched - English runs through the file overlay "
                  "(no hook); run install.sh or apply-en.py --apply")

    env = {
        "SEGATOOLS_CONFIG_PATH": "Z:" + target.replace("/", "\\"),
        "FGO_INSTALL_ROOT": install,
        "FGO_TARGET_FPS": str(cfg["fps"]),
        "FGO_LOCAL_NETWORK": "1",
        "FGO_LOCAL_HTTP_PORT": str(PORTS["http"]),
        "FGO_LOCAL_BILLING_PORT": str(PORTS["billing"]),
        "FGO_LOCAL_AIME_PORT": str(PORTS["aime"]),
        "FGO_PRINT_METADATA_ONLY": "1",
        "FGO_ZH_ENABLED": "1" if zh_hook else "0",
        # shared memory the launcher publishes the deck into (formula from GameCommunication.cs)
        "FGO_DECK_CHANNEL": "FGODeck_" + hashlib.sha256(
            game.rstrip("\\").upper().encode("utf-8")).hexdigest().upper(),
        "DRIRC_CONFIGDIR": DRIRC_DIR,
    }
    if not os.path.isdir(DRIRC_DIR):
        print(f"warning: no Mesa config at {DRIRC_DIR} - the game's shaders will most likely fail",
              file=sys.stderr)
    if cfg["mode"] == "borderless":
        env["__COMPAT_LAYER"] = "DISABLEDXMAXIMIZEDWINDOWEDMODE"
        env["FGO_BORDERLESS_COMPOSED"] = "1"

    G = game
    args = ["inject.exe", "-d", "-k", G + "\\fgoglcompat.dll", "-k", G + "\\fgohook.dll"]
    if zh_hook:
        args += ["-k", G + "\\zh\\fgozh.dll"]
    args += [G + "\\ago.exe", native_render_argument(cfg["width"], cfg["height"])]
    if cfg["cabinet"] != "saved":
        # as in FGO_Launcher.ps1: -sm <server|satellite> goes right after the native argument
        args += ["-sm", cfg["cabinet"]]
    if windowed:
        args.append("-w")
    args.append("--wasapi-shared")

    if "--print-args" in sys.argv:
        for key, value in env.items():
            print(f"export {key}={sh_quote(value)}")
        print(f"# cabinet: {cfg['cabinet']}")
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
