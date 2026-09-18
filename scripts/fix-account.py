#!/usr/bin/env python3
"""A proper account instead of the "unbound" card (otherwise the launcher throws errors).

When the game was started with an empty DEVICE/aime.txt it creates an account with
aime_id 0xFFFFFFFF. The launcher reads aime_id as int32 and throws on it inside
RefreshAccountsAsync, reopening the modal dialog on a timer. This script finds such records
in Server/state/fgo-players.json, creates a proper account with the platform's own tool when
needed, points the card at it and removes the broken record (keeping a profile backup).

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
    """Runs fgo_account.py inside Wine (Windows python), the way the launcher does."""
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
        print(f"no player profile: {profile_path}", file=sys.stderr)
        return 1
    profile = load_profile(profile_path)
    bad = bogus_ids(profile)
    if not bad:
        print("no broken accounts - nothing to do")
        return 0
    print("found problematic accounts (aime_id does not fit int32): "
          + ", ".join(key for key, _ in bad))

    if not port_open(8889):
        print("MariaDB is not running - bringing the server up through scripts/server.sh")
        here = os.path.dirname(os.path.abspath(__file__))
        subprocess.run(["bash", os.path.join(here, "server.sh")], timeout=240)

    listing, _code = tool(root, "list", "--json")
    good = [acc for acc in listing.get("accounts", [])
            if 0 < int(acc.get("aime_id", 0)) <= INT32_MAX]
    if good:
        target = good[0]["aime_id"]
        print(f"a normal account already exists, aime_id={target} - using it")
    else:
        print("creating the MASTER account (mode normal)")
        created, _code = tool(root, "create", "--name", "MASTER", "--mode", "normal",
                              "--json", "--force")
        target = (created.get("account") or created).get("aime_id")
        if not target:
            print(f"could not create the account: {created}", file=sys.stderr)
            return 1

    used, _code = tool(root, "use", "--aime-id", str(target), "--json")
    if not used.get("ok"):
        print(f"could not point DEVICE/aime.txt at account {target}: {used}", file=sys.stderr)
        return 1
    print(f"DEVICE/aime.txt now points at account {target}")

    backup = f"{profile_path}.bak-fix-account-{time.strftime('%Y%m%d-%H%M%S')}"
    shutil.copyfile(profile_path, backup)
    for key, _aime_id in bad:
        profile.pop(key, None)
    with open(profile_path, "w", encoding="utf-8") as fh:
        json.dump(profile, fh, ensure_ascii=False, indent=2)
    print(f"broken records removed from the profile (backup: {os.path.basename(backup)})")
    print("done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
