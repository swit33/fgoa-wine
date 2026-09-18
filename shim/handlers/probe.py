#!/usr/bin/env python3
"""The PowerShell version probe run by PowerShellHost.Find().

The launcher expects exit code 0 (64-bit, version >= 5.1, not 6). We are not PowerShell,
but we honour the contract: 0 = "a suitable host was found".
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402

common.log_call("probe", sys.argv[1:])
sys.exit(0)
