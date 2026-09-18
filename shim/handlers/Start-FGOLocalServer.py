#!/usr/bin/env python3
"""Start-FGOLocalServer.ps1 — поднять MariaDB + ARTEMiS и дождаться готовности.

Поведение как у оригинала:
  * берём лок Server/state/server-start.lock — второй запуск, пока идёт первый, ничего
    не поднимает, а ждёт готовности (у оригинала это исключение [FGO-SERVER:BUSY]);
  * печатаем прогресс: лончер стримит наш вывод в свою панель логов, и именно это
    отличает «кнопка сделала что-то и работает» от «ничего не произошло, нажму ещё раз»;
  * ждём порты (у оригинала Wait-TcpPort с таймаутом 30 с на порт);
  * и только потом объявляем готовность, после health-check'а ALL.Net ("Service OK").

Тайминги важны. Лончер ждёт наш процесс не больше 120 секунд
(MainWindow.ExecuteServerCommandAsync, TimeSpan.FromSeconds(start ? 120 : 50)), поэтому и
удерживающий старт, и ожидающий чужой старт обязаны уложиться в это окно: если вернуть
ненулевой код, лончер покажет «Server Did Not Start» и сбросит статус на
«Server ports down/down/down». Отсюда HOLDER_TIMEOUT и WAIT_TIMEOUT ниже.

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
WAIT_TIMEOUT = 110                 # ожидание чужого старта; лончер терпит 120 с
HOLDER_TIMEOUT = 105               # сколько даём server.sh на своём старте
HEALTH_TIMEOUT = 5
STALE_LOCK_SECONDS = 150           # лок без движения дольше этого — зависший старт


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


def try_lock(path):
    """-> (файл, True) если лок наш; (файл, False) если его держит кто-то другой.
    Режим "a": open(..., "w") обнулил бы файл и обновил mtime, а по нему мы считаем
    лок зависшим."""
    handle = open(path, "a")
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return handle, False
    return handle, True


def lock_is_stale(path):
    """Лок без движения дольше STALE_LOCK_SECONDS — старт, который уже никуда не идёт."""
    try:
        return time.time() - os.path.getmtime(path) > STALE_LOCK_SECONDS
    except OSError:
        return False


def start_server():
    """Поднимаем сервер (лок уже наш). -> код возврата для лончера."""
    began = time.time()
    print("Starting the local server: MariaDB, then ARTEMiS. This takes up to about 30 seconds "
          "after a stop - please do not press Start again, this window stays busy until the "
          "server answers.", flush=True)
    code = common.run(["bash", common.script("server.sh")], timeout=HOLDER_TIMEOUT)
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


def wait_for_other_start():
    """Сервер поднимает чужой запуск: ждём его, ничего не поднимая сами. -> код возврата."""
    print("Another press of Start is already bringing the server up. Waiting for it - "
          "nothing to do here, and this window stays busy until it answers.", flush=True)
    if not wait_ports(WAIT_TIMEOUT) or not health_ok():
        print(f"The start that was already running did not bring the server up within {WAIT_TIMEOUT}s. "
              "See /tmp/mariadb.log, /tmp/artemis.log and logs/server-control.log.", file=sys.stderr)
        return 10
    ready_message(0)
    return 0


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

    stale = lock_is_stale(lock_path)      # считаем до открытия, иначе mtime обновится
    lock, ours = try_lock(lock_path)
    if not ours and stale:
        print(f"{os.path.basename(lock_path)} has not moved for more than {STALE_LOCK_SECONDS}s - "
              "that start is not going anywhere. Taking over.", flush=True)
        lock.close()
        try:
            os.unlink(lock_path)
        except OSError:
            pass
        lock, ours = try_lock(lock_path)
    if not ours:
        lock.close()
        return wait_for_other_start()

    try:
        os.utime(lock_path, None)          # отметка живого старта
        return start_server()
    finally:
        fcntl.flock(lock, fcntl.LOCK_UN)
        lock.close()


if __name__ == "__main__":
    sys.exit(main())
