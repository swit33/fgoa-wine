#!/usr/bin/env python3
"""Server watcher: does nothing while the launcher lives, stops the server when it exits.

Started detached from the Stop-FGOLocalServerWhenIdle handler (its own session, output to
/tmp/fgoa-server-watch.log), so it does not get in the launcher's way or hold its pipes.
"""
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402

MAX_LIFETIME = 24 * 3600


def launcher_alive():
    # [.] inside the pattern so pgrep does not match its own argument
    return subprocess.run(["pgrep", "-f", "FGOAC scooby[.]exe"],
                          stdout=subprocess.DEVNULL).returncode == 0


def main():
    common.log("stop-watcher: started")
    deadline = time.time() + MAX_LIFETIME
    while time.time() < deadline:
        time.sleep(10)
        if not launcher_alive():
            common.log("stop-watcher: launcher is gone, stopping the server")
            common.run(["bash", common.script("server.sh"), "stop"], timeout=120)
            return 0
    common.log("stop-watcher: lifetime exceeded, leaving the server as it is")
    return 0


if __name__ == "__main__":
    sys.exit(main())
