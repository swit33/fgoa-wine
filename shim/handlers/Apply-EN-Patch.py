#!/usr/bin/env python3
"""Apply-EN-Patch.ps1 — накат и откат английского набора.

Зовут из FirstRun и из апдейтера (после обновления релиза лончер распаковывает новый
payload и просит применить его). Коды возврата повторяют документированные в оригинальном
скрипте: 0 — применено (или уже стоит), 2 — не похоже на установку, 5 — набор не сошёлся,
7 — откатывать нечего, 9 — нет обновления Cloud23333 (V1.01+).
"""
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402


def resolve_root(argv):
    given = common.arg_value(argv, "-InstallRoot")
    if given:
        return common.host_path(given)
    return common.install_root()


def rollback(root):
    backup = os.path.join(root, "_en-overlay-backup")
    ago_backup = os.path.join(root, "App", "ago.exe.en-overlay.bak")
    marker = os.path.join(root, "App", "zh", "en-patch.json")
    if not os.path.isdir(backup) and not os.path.isfile(ago_backup):
        print("There is no English patch backup to restore.", file=sys.stderr)
        return 7
    restored = 0
    for dirpath, _dirs, files in os.walk(backup):
        for name in files:
            src = os.path.join(dirpath, name)
            dst = os.path.join(root, os.path.relpath(src, backup))
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copyfile(src, dst)
            restored += 1
    if os.path.isfile(ago_backup):
        shutil.copyfile(ago_backup, os.path.join(root, "App", "ago.exe"))
        restored += 1
    if os.path.isfile(marker):
        os.unlink(marker)
    print(f"Rollback complete: {restored} files restored from _en-overlay-backup/.")
    print("Files the patch added where the game had none are left in place.")
    return 0


def main():
    argv = sys.argv[1:]
    common.log_call("Apply-EN-Patch", argv)
    root = os.path.realpath(resolve_root(argv))
    common.log(f"apply-en: root={root} rollback={common.has_flag(argv, '-Rollback')}")

    if not os.path.isdir(os.path.join(root, "Server", "tools")):
        print(f"This is not an FGO Arcade install: {root}", file=sys.stderr)
        return 2
    if not os.path.isfile(os.path.join(root, "App", "FGO_Runtime.dll")):
        print("This game folder has not had Cloud23333's V1.01 (or V1.02) update yet: "
              "App\\FGO_Runtime.dll is missing. Apply his update first.", file=sys.stderr)
        return 9
    if common.has_flag(argv, "-Rollback"):
        return rollback(root)

    print(f"[apply-en] applying the English dataset to {root}")
    code = common.run(["python3", common.script("apply-en.py"), root, "--apply"])
    if code != 0:
        print("[apply-en] the dataset did not verify — see the report above.", file=sys.stderr)
        return 5
    print("[apply-en] done: resources overlaid and ago.exe strings patched.")
    code = common.run(["python3", common.script("patch-server.py"), root, "--apply"])
    if code != 0:
        print("[apply-en] server-side fixes did not apply — see the report above.", file=sys.stderr)
        return 5
    print("[apply-en] server-side fixes in place (account CLI log level, upgrade indexing).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
