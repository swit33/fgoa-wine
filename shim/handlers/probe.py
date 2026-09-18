#!/usr/bin/env python3
"""Проба версии PowerShell, которую делает PowerShellHost.Find().

Лончер ждёт код возврата 0 (64-бит, версия >= 5.1, не 6). Мы — не PowerShell, но
контракт соблюдаем: 0 = «подходящий хост найден».
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402

common.log_call("probe", sys.argv[1:])
sys.exit(0)
