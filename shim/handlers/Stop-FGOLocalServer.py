#!/usr/bin/env python3
"""Stop-FGOLocalServer.ps1 - stop MariaDB and ARTEMiS."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402


def main():
    common.log_call("Stop-FGOLocalServer", sys.argv[1:])
    return common.run(["bash", common.script("server.sh"), "stop"], timeout=120)


if __name__ == "__main__":
    sys.exit(main())
