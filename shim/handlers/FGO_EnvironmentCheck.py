#!/usr/bin/env python3
"""FGO_EnvironmentCheck.ps1 — отчёт об окружении.

Лончер показывает этот текст на странице Diagnostics and Help. Смысл — честно сказать,
что есть, чего нет и что под Wine проверено быть не может (аудио-эндпоинты и реестр
Windows не эмулируются, поэтому эти пункты помечаем отдельно, а не выдумываем).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402

REQUIRED = [
    "App/ago.exe", "App/am/amdaemon.exe", "App/fgohook.dll", "App/FGO_Runtime.dll",
    "App/inject.exe", "App/config.json", "App/segatools.ini",
    "App/Tools/Locale_Remulator/LRHookx64.dll",
    "AMFS/ICF1", "AMFS/ICF2", "DEVICE/runtime/segatools.runtime.ini",
    "Server/python/python.exe", "Server/mariadb.ini",
    "Server/mariadb-10.11.16-winx64/bin/mariadbd.exe",
    "Server/artemis/config/core.yaml",
]
FOLDERS = ["App", "AMFS", "GameData", "DEVICE", "logs", "Server/state"]
PORTS = [("ALL.Net", 777), ("billing", 9999), ("AimeDB", 7777), ("MariaDB", 8889)]
EN_PATCH = "App/zh/en-patch.json"
OVERLAY_BACKUP = "_en-overlay-backup"
AGO_BACKUP = "App/ago.exe.en-overlay.bak"


def main():
    common.log_call("FGO_EnvironmentCheck", sys.argv[1:])
    root = common.install_root()
    print("FGO Arcade environment check (Linux/Wine, via fgoa-wine)")
    print(f"Install root: {root}")
    print()

    missing = [rel for rel in REQUIRED if not os.path.isfile(os.path.join(root, rel))]
    print(f"[{'OK' if not missing else 'FAIL'}] Game and server files: "
          f"{len(REQUIRED) - len(missing)}/{len(REQUIRED)} present")
    for rel in missing:
        print(f"        missing: {rel}")

    unwritable = []
    for rel in FOLDERS:
        path = os.path.join(root, rel)
        try:
            os.makedirs(path, exist_ok=True)
            probe = os.path.join(path, f".fgo-env-{os.getpid()}")
            with open(probe, "w", encoding="utf-8") as fh:
                fh.write("check")
            os.unlink(probe)
        except OSError as exc:
            unwritable.append((rel, exc))
    print(f"[{'OK' if not unwritable else 'FAIL'}] Folder permissions: "
          f"{len(FOLDERS) - len(unwritable)}/{len(FOLDERS)} writable")
    for rel, exc in unwritable:
        print(f"        cannot write {rel}: {exc}")

    listening = [(name, port, common.port_open(port)) for name, port in PORTS]
    running = [name for name, _port, ok in listening if ok]
    print(f"[{'OK' if len(running) >= 3 else 'INFO'}] Local server: "
          f"{', '.join(running) if running else 'not running'}")
    for name, port, ok in listening:
        print(f"        {name:<8} port {port}: {'listening' if ok else 'closed'}")

    en = os.path.isfile(os.path.join(root, EN_PATCH))
    print(f"[{'OK' if en else 'INFO'}] English dataset: "
          f"{'applied (App/zh/en-patch.json present)' if en else 'not applied — run scripts/apply-en.py'}")
    print(f"        backups: {'yes' if os.path.isdir(os.path.join(root, OVERLAY_BACKUP)) else 'no'} "
          f"({OVERLAY_BACKUP}/, {'yes' if os.path.isfile(os.path.join(root, AGO_BACKUP)) else 'no'} "
          f"{AGO_BACKUP})")

    print()
    print("Not checked here (Windows-only APIs, emulated by Wine): Windows media components,")
    print("the audio service and output endpoints, drive letters other than Z: / C:.")
    print("The game itself reports the cabinet checks (touch panel, LED, card reader, printer)")
    print("on its SYSTEM STARTUP screen.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
