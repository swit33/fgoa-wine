"""Bypasses fgo_server_config's guard: its `apply` treats "server is running" as true when any
of the current ports is busy. On this machine docker holds 8888 (not our server), so we call
the same function with check_running=False - the write format stays the official one (core.yaml,
fgo-launcher.json, segatools.ini and mariadb.ini are edited consistently).

Runs under the Windows python inside Wine:

  wine 'Z:\\...\\Server\\python\\python.exe' scripts/set-ports.py [http] [database]

The install root comes from FGOA_WIN_ROOT (defaults to Z:\\mnt\\misc\\games\\fgoa\\FGOA).
"""
import os
import sys

root = os.environ.get("FGOA_WIN_ROOT", "Z:\\mnt\\misc\\games\\fgoa\\FGOA")
sys.path.insert(0, os.path.join(root, "Server", "tools"))
import fgo_server_config as cfg  # noqa: E402

http = int(sys.argv[1]) if len(sys.argv) > 1 else 777
db = int(sys.argv[2]) if len(sys.argv) > 2 else 8889
values = dict(host="auto", http=http, billing=9999, aime=7777, database=db)
print(cfg.apply(values, check_running=False))
