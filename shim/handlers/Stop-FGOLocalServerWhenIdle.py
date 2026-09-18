#!/usr/bin/env python3
"""Stop-FGOLocalServerWhenIdle.ps1 - a watcher: the server goes down with the launcher.

The launcher starts us in the background and does not wait. We must not hold its stdout
pipes: after the script stops it waits for EOF. So we spawn a separate process (its own
session, output to a file) and exit right away.

-FrontendProcessId (a Windows PID) is useless here: PIDs under Wine and on Linux are
numbered differently, so the launcher process is looked up by name instead.
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
