"""Обход защиты fgo_server_config: его `apply` считает «сервер запущен», если занят
любой из текущих портов. На этой машине 8888 держит докер (не наш сервер), поэтому зовём
его же функцию с check_running=False — формат записи остаётся штатным (core.yaml,
fgo-launcher.json, segatools.ini, mariadb.ini правятся согласованно).

Запускается под Windows-python внутри Wine:

  wine 'Z:\\...\\Server\\python\\python.exe' scripts/set-ports.py [http] [database]

Корень установки берётся из FGOA_WIN_ROOT (по умолчанию Z:\\mnt\\misc\\games\\fgoa\\FGOA).
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
