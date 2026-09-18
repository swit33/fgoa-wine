#!/usr/bin/env python3
"""Test-FgoWritableLayout - checks that every working folder of the game is writable.

The launcher calls this as `pwsh -Command "... . $env:FGO_CHECK_SCRIPT; Test-FgoWritableLayout
-InstallRoot $env:FGO_CHECK_ROOT"` and shows any non-zero exit code to the player as
"error 4" (folder blocked) together with our output. Hence:
  * folders are created, a probe file is written and removed;
  * read-only is cleared from files and folder contents (unpacked archives arrive with
    that flag);
  * on success a short report and exit 0; on failure a readable line and exit code 4.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402

FOLDERS = ["App", "AMFS", "GameData", "DEVICE", "DEVICE/runtime", "DEVICE/print",
           "logs", "Server/state", "Server/artemis/config", "Server/data/mariadb"]
FILES = ["App/fgo-launcher.json", "App/deck.json", "App/segatools.ini",
         "Server/mariadb.ini", "Server/artemis/config/core.yaml"]
CLEAR_READONLY = ["AMFS", "GameData", "DEVICE", "Server/state", "Server/data/mariadb"]


def install_root():
    """The root comes from the launcher environment (FGO_CHECK_ROOT), else from the shim config."""
    from_env = os.environ.get("FGO_CHECK_ROOT")
    if from_env:
        return common.host_path(from_env)
    return common.install_root()


def main():
    root = os.path.realpath(install_root())
    common.log_call("FGO_StartupChecks", sys.argv[1:])
    common.log(f"writable-layout: root={root}")
    problems = []
    checked = 0
    for rel in FOLDERS:
        path = os.path.join(root, rel)
        try:
            os.makedirs(path, exist_ok=True)
            probe = os.path.join(path, f".fgo-write-{os.getpid()}-{os.urandom(4).hex()}")
            with open(probe, "w", encoding="utf-8") as fh:
                fh.write("write check")
            os.unlink(probe)
            checked += 1
        except OSError as exc:
            problems.append(f"[FGO-LAUNCHER:4] Cannot write to {path}: {exc}")
    for rel in FILES:
        path = os.path.join(root, rel)
        if not os.path.isfile(path):
            continue
        try:
            mode = os.stat(path).st_mode
            os.chmod(path, mode | 0o600)
            with open(path, "r+b"):
                pass
        except OSError as exc:
            problems.append(f"[FGO-LAUNCHER:4] Cannot open {path} for writing: {exc}")
    cleared = 0
    for rel in CLEAR_READONLY:
        for dirpath, _dirs, files in os.walk(os.path.join(root, rel)):
            for name in files:
                path = os.path.join(dirpath, name)
                try:
                    mode = os.stat(path).st_mode
                    if not mode & 0o200:
                        os.chmod(path, mode | 0o200)
                        cleared += 1
                except OSError:
                    pass

    if problems:
        for line in problems:
            print(line, file=sys.stderr)
        print(f"Writable layout check failed in {len(problems)} place(s).", file=sys.stderr)
        return 4
    print(f"Writable layout OK: {checked} folders, {len(FILES)} config files, "
          f"{cleared} files had the read-only flag cleared.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
