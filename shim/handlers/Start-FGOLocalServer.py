#!/usr/bin/env python3
"""Start-FGOLocalServer.ps1 — поднять MariaDB + ARTEMiS и дождаться готовности.

Поведение как у оригинала:
  * берём лок Server/state/server-start.lock — второй запуск, пока идёт первый, ничего
    не поднимает, а ждёт готовности (у оригинала это исключение [FGO-SERVER:BUSY]);
  * печатаем прогресс: лончер стримит наш вывод в свою панель логов, и именно это
    отличает «кнопка сделала что-то и работает» от «ничего не произошло, нажму ещё раз»;
  * ждём порты (у оригинала Wait-TcpPort с таймаутом 30 с на порт);
  * и только потом объявляем готовность, после health-check'а ALL.Net ("Service OK").

Ненулевой код лончер показывает как «ошибку 10» (локальный сервер не поднялся).
Аргумент -ServerHost игнорируем: адрес и порты заданы в конфигах установки
(Server/mariadb.ini, artemis/config/core.yaml, App/segatools.ini).
"""
import fcntl
import os
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402

HTTP_PORT = 777
PORTS = (777, 9999, 7777)          # ALL.Net, billing, AimeDB
PORT_TIMEOUT = 30                  # как Wait-TcpPort -TimeoutSeconds 30
HEALTH_TIMEOUT = 5


def ready_message(seconds):
    print(f"FGO local server is ready at 127.0.0.1 ({PORTS[0]}/{PORTS[1]}/{PORTS[2]}), "
          f"ports answered after {seconds:.0f}s.")


def health_ok():
    """Оригинал делает GET http://127.0.0.1:<http>/ и ждёт 200 + "Service OK"."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{HTTP_PORT}/", timeout=HEALTH_TIMEOUT) as answer:
            body = answer.read().decode("utf-8", "replace")
            return answer.status == 200 and "Service OK" in body
    except (urllib.error.URLError, OSError):
        return False


def wait_ports(timeout=PORT_TIMEOUT, quiet=False):
    """Ждём, пока откроются все три порта. -> True/False."""
    start = time.time()
    while time.time() - start < timeout:
        if all(common.port_open(port) for port in PORTS):
            return True
        if not quiet:
            missing = [str(p) for p in PORTS if not common.port_open(p)]
            print(f"  waiting for the local server: closed ports {', '.join(missing)}", flush=True)
        time.sleep(2)
    return False


def main():
    argv = sys.argv[1:]
    common.log_call("Start-FGOLocalServer", argv)
    state_dir = os.path.join(common.install_root(), "Server", "state")
    os.makedirs(state_dir, exist_ok=True)
    lock_path = os.path.join(state_dir, "server-start.lock")

    if all(common.port_open(port) for port in PORTS) and health_ok():
        print("The local server is already running.")
        ready_message(0)
        return 0

    lock = open(lock_path, "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print("Another start is already in progress (server-start.lock is held): "
              "waiting for it instead of starting a second MariaDB/ARTEMiS.", flush=True)
        if not wait_ports() or not health_ok():
            print("The start that held the lock did not finish in time. "
                  "See /tmp/mariadb.log and /tmp/artemis.log.", file=sys.stderr)
            return 10
        ready_message(0)
        return 0

    try:
        began = time.time()
        print("Starting the local server: MariaDB, then ARTEMiS ...", flush=True)
        code = common.run(["bash", common.script("server.sh")], timeout=240)
        if code != 0:
            print("The local server did not start. See /tmp/mariadb.log and /tmp/artemis.log.",
                  file=sys.stderr)
            return 10
        # server.sh сам ждёт порты, здесь только добираем остаток и проверяем здоровье
        if not wait_ports(timeout=5):
            print("The local server did not open all of its ports in time.", file=sys.stderr)
            return 10
        if not health_ok():
            print("The local ALL.Net service did not pass its health check (expected \"Service OK\").",
                  file=sys.stderr)
            return 10
        ready_message(time.time() - began)
        return 0
    finally:
        fcntl.flock(lock, fcntl.LOCK_UN)
        lock.close()


if __name__ == "__main__":
    sys.exit(main())
