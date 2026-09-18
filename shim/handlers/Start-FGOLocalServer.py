#!/usr/bin/env python3
"""Start-FGOLocalServer.ps1 - bring MariaDB + ARTEMiS up and wait until they are ready.

Behaviour matches the original:
  * a lock at Server/state/server-start.lock: a second start while the first is running
    starts nothing and waits instead (the original throws [FGO-SERVER:BUSY]);
  * we print progress: the launcher streams our output into its log panel, and that is
    what separates "the button did something" from "nothing happened, press again";
  * we wait for the ports (the original uses Wait-TcpPort, 30 s per port);
  * and only then declare readiness, after an ALL.Net health check ("Service OK").

Timings matter. The launcher waits for our process no longer than 120 seconds
(MainWindow.ExecuteServerCommandAsync, TimeSpan.FromSeconds(start ? 120 : 50)), so both
the start that holds the lock and the one waiting for it must fit that window: a non-zero
exit code makes the launcher show "Server Did Not Start" and drop the status back to
"Server ports down/down/down". Hence HOLDER_TIMEOUT and WAIT_TIMEOUT below.

A non-zero code is shown as "error 10" (the local server did not come up).
-ServerHost is ignored: the address and ports live in the install's own configs
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
PORT_TIMEOUT = 30                  # same as Wait-TcpPort -TimeoutSeconds 30
WAIT_TIMEOUT = 110                 # waiting for another start; the launcher tolerates 120s
HOLDER_TIMEOUT = 105               # how long our own server.sh start may take
HEALTH_TIMEOUT = 5
STALE_LOCK_SECONDS = 150           # a lock idle longer than this is a wedged start


def ready_message(seconds):
    print(f"FGO local server is ready at 127.0.0.1 ({PORTS[0]}/{PORTS[1]}/{PORTS[2]}), "
          f"ports answered after {seconds:.0f}s.")


def health_ok():
    """The original does GET http://127.0.0.1:<http>/ and expects 200 + "Service OK"."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{HTTP_PORT}/", timeout=HEALTH_TIMEOUT) as answer:
            body = answer.read().decode("utf-8", "replace")
            return answer.status == 200 and "Service OK" in body
    except (urllib.error.URLError, OSError):
        return False


def wait_ports(timeout=PORT_TIMEOUT, quiet=False):
    """Wait until all three ports answer. -> True/False."""
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
    """-> (handle, True) when the lock is ours; (handle, False) when someone holds it.
    Mode "a": open(..., "w") would truncate the file and refresh its mtime, and that mtime
    is how a wedged lock is recognised."""
    handle = open(path, "a")
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return handle, False
    return handle, True


def lock_is_stale(path):
    """A lock idle longer than STALE_LOCK_SECONDS - a start that is going nowhere."""
    try:
        return time.time() - os.path.getmtime(path) > STALE_LOCK_SECONDS
    except OSError:
        return False


def start_server():
    """Start the server (the lock is ours). -> the exit code for the launcher."""
    began = time.time()
    print("Starting the local server: MariaDB, then ARTEMiS. This takes up to about 30 seconds "
          "after a stop - please do not press Start again, this window stays busy until the "
          "server answers.", flush=True)
    code = common.run(["bash", common.script("server.sh")], timeout=HOLDER_TIMEOUT)
    if code != 0:
        print("The local server did not start. See /tmp/mariadb.log and /tmp/artemis.log.",
              file=sys.stderr)
        return 10
    # server.sh already waits for the ports; here we only top up and check the health
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
    """Another start is bringing the server up: wait for it without starting anything."""
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

    stale = lock_is_stale(lock_path)      # read before opening, or the mtime is refreshed
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
        os.utime(lock_path, None)          # mark a live start
        return start_server()
    finally:
        fcntl.flock(lock, fcntl.LOCK_UN)
        lock.close()


if __name__ == "__main__":
    sys.exit(main())
