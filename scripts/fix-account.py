#!/usr/bin/env python3
"""Нормальный аккаунт вместо «непривязанной» карты (иначе лончер сыпет ошибками).

Если игру запустили с пустым DEVICE/aime.txt, она заводит аккаунт с aime_id 0xFFFFFFFF.
Лончер читает aime_id как int32 и падает на нём в RefreshAccountsAsync — открывая модальный
диалог по таймеру. Скрипт: находит такие записи в Server/state/fgo-players.json, при
необходимости создаёт нормальный аккаунт их же тулзой, направляет на него карту и убирает
битую запись (с бэкапом профиля).

  python3 fix-account.py [install_root]
"""
import json
import os
import shutil
import subprocess
import sys
import time

REPO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INT32_MAX = 2147483647
BOGUS = 4294967295


def win(path):
    return "Z:" + os.path.abspath(path).replace("/", "\\")


def port_open(port):
    import socket
    with socket.socket() as sock:
        sock.settimeout(0.4)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def load_profile(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def bogus_ids(profile):
    out = []
    for key, value in profile.items():
        if isinstance(key, str) and key.startswith("aime:"):
            try:
                aime_id = int(key.split(":", 1)[1])
            except ValueError:
                continue
            if aime_id > INT32_MAX or aime_id == BOGUS:
                out.append((key, aime_id))
    return out


def tool(root, *args, timeout=180):
    """Вызов fgo_account.py внутри Wine (Windows-питон), как это делает лончер."""
    python = win(os.path.join(root, "Server", "python", "python.exe"))
    script = win(os.path.join(root, "Server", "tools", "fgo_account.py"))
    cmd = ["wine", python, script, *args]
    env = dict(os.environ, WINEPREFIX=os.environ.get("WINEPREFIX", os.path.expanduser("~/.fgoa-test")),
               WINEDEBUG="-all")
    proc = subprocess.run(cmd, cwd=os.path.join(root, "Server", "artemis"),
                          env=env, capture_output=True, text=True, timeout=timeout)
    out = [line for line in proc.stdout.splitlines() if line.startswith("{")]
    return (json.loads(out[-1]) if out else {}), proc.returncode


def main():
    root = os.path.abspath(sys.argv[1] if len(sys.argv) > 1
                           else os.environ.get("FGOA_ROOT") or os.path.abspath(os.path.join(REPO_DIR, os.pardir)))
    profile_path = os.path.join(root, "Server", "state", "fgo-players.json")
    if not os.path.isfile(profile_path):
        print(f"нет профиля игроков: {profile_path}", file=sys.stderr)
        return 1
    profile = load_profile(profile_path)
    bad = bogus_ids(profile)
    if not bad:
        print("битых аккаунтов нет — ничего делать не нужно")
        return 0
    print("найдены проблемные аккаунты (aime_id не влезает в int32): "
          + ", ".join(key for key, _ in bad))

    if not port_open(8889):
        print("MariaDB не запущена — поднимаю сервер через scripts/server.sh")
        here = os.path.dirname(os.path.abspath(__file__))
        subprocess.run(["bash", os.path.join(here, "server.sh")], timeout=240)

    listing, _code = tool(root, "list", "--json")
    good = [acc for acc in listing.get("accounts", [])
            if 0 < int(acc.get("aime_id", 0)) <= INT32_MAX]
    if good:
        target = good[0]["aime_id"]
        print(f"уже есть нормальный аккаунт aime_id={target}, беру его")
    else:
        print("создаю аккаунт MASTER (mode normal)")
        created, _code = tool(root, "create", "--name", "MASTER", "--mode", "normal",
                              "--json", "--force")
        target = (created.get("account") or created).get("aime_id")
        if not target:
            print(f"не удалось создать аккаунт: {created}", file=sys.stderr)
            return 1

    used, _code = tool(root, "use", "--aime-id", str(target), "--json")
    if not used.get("ok"):
        print(f"не удалось направить DEVICE/aime.txt на аккаунт {target}: {used}", file=sys.stderr)
        return 1
    print(f"DEVICE/aime.txt теперь указывает на аккаунт {target}")

    backup = f"{profile_path}.bak-fix-account-{time.strftime('%Y%m%d-%H%M%S')}"
    shutil.copyfile(profile_path, backup)
    for key, _aime_id in bad:
        profile.pop(key, None)
    with open(profile_path, "w", encoding="utf-8") as fh:
        json.dump(profile, fh, ensure_ascii=False, indent=2)
    print(f"битые записи убраны из профиля (бэкап: {os.path.basename(backup)})")
    print("готово")
    return 0


if __name__ == "__main__":
    sys.exit(main())
