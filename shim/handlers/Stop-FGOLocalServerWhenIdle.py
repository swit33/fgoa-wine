#!/usr/bin/env python3
"""Stop-FGOLocalServerWhenIdle.ps1 — сторож: сервер гаснет, когда лончер закрыли.

Лончер запускает нас «в фоне» и не ждёт. Держать его stdout-пайпы нельзя: лончер после
остановки скрипта ждёт EOF. Поэтому заводим отдельный процесс (своя сессия, вывод в файл)
и сразу выходим.

Аргумент -FrontendProcessId (Windows-PID) здесь бесполезен — нумерация PID у Wine и Linux
разная, поэтому проверяем наличие процесса лончера по имени.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402


def main():
    common.log_call("Stop-FGOLocalServerWhenIdle", sys.argv[1:])
    common.spawn_detached(["python3", common.script("stop-watcher.py")],
                          "/tmp/fgoa-server-watch.log")
    print("Idle watcher started: the local server stops when FGOAC scooby exits.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
