#!/usr/bin/env python3
"""Start-FGOLocalServer.ps1 — поднять MariaDB + ARTEMiS.

Лончер стримит наш вывод в панель логов, а ненулевой код показывает как «ошибку 10»
(локальный сервер не поднялся). Аргумент -ServerHost игнорируем: адрес и порты заданы
в конфигах установки (Server/mariadb.ini, artemis/config/core.yaml, App/segatools.ini).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402


def main():
    common.log_call("Start-FGOLocalServer", sys.argv[1:])
    code = common.run(["bash", common.script("server.sh")], timeout=240)
    if code != 0:
        print("The local server did not start. See /tmp/mariadb.log and /tmp/artemis.log.", file=sys.stderr)
        return 10
    return 0


if __name__ == "__main__":
    sys.exit(main())
