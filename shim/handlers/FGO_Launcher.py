#!/usr/bin/env python3
"""FGO_Launcher.ps1 — кнопка Play: подготовить игру и запустить её через inject.exe.

Лончер читает наш вывод в панель логов и отпускает кнопку только по EOF. Поэтому игру
запускаем отсоединённо (common.spawn_detached): свой лог, своя сессия, exit 0 сразу —
ровно как оригинальный скрипт, который уводит игру в фон и возвращает управление. Если
ждать игру (как было раньше), кнопка «залипает» на всю сессию: нажатия копятся, и каждое
следующее запускает ещё один экземпляр — вместе с ещё одним сервером и ещё одним инжектом.

Перед запуском гасим остатки прошлой сессии из этой же установки (ago/amdaemon/inject) —
то же, что делает FGO_Launcher.ps1 через Get-Process ... | Stop-Process -Force.

Оригинальный скрипт сам поднимает сервер (autoStartLocalServer), иначе игра не дойдёт до
титульного экрана и покажет ERROR 4102.

Колода: лончер сам кладёт её в разделяемую память FGO_DECK_<sha256 пути App>, имя канала
игра узнаёт из FGO_DECK_CHANNEL (её ставит scripts/launch.py; формула взята из
FGOLocalPlatform/DeckReaderUI.Kancolle/GameCommunication.cs).
"""
import os
import signal
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402

ARG_MAP = (("-DisplayMode", "--mode"), ("-ResolutionWidth", "--width"),
           ("-ResolutionHeight", "--height"), ("-InputMode", "--input"),
           ("-TargetFps", "--fps"))
GAME_PROCESSES = ("ago.exe", "amdaemon.exe", "inject.exe")


def kill_leftovers():
    """Процессы прошлой сессии этой установки. Под Wine их видно по имени exe."""
    killed = []
    for name in GAME_PROCESSES:
        try:
            pids = subprocess.run(["pgrep", "-x", name], capture_output=True,
                                  text=True).stdout.split()
        except OSError:
            return killed
        for pid in pids:
            try:
                os.kill(int(pid), signal.SIGKILL)
                killed.append(f"{name}({pid})")
            except (ProcessLookupError, PermissionError, ValueError):
                pass
    if killed:
        print("[fgoa-wine] stopped processes from the previous session: " + ", ".join(killed))
    return killed


def main():
    argv = sys.argv[1:]
    common.log_call("FGO_Launcher", argv)
    kill_leftovers()

    if not all(common.port_open(port) for port in (777, 9999, 7777)):
        print("[fgoa-wine] local server is not running - starting it (MariaDB + ARTEMiS)")
        if common.run(["bash", common.script("server.sh")], timeout=240) != 0:
            print("[fgoa-wine] the local server did not start; expect ERROR 4102 in the game",
                  file=sys.stderr)

    cmd = ["python3", "-u", common.script("launch.py"), common.install_root(), "--run"]
    for flag, option in ARG_MAP:
        value = common.arg_value(argv, flag)
        if value:
            cmd += [option, value]

    log_file = common.launch_log_path()
    print(f"[fgoa-wine] deck channel: {common.deck_channel()}")
    print("[fgoa-wine] starting the game (inject.exe + fgoglcompat + fgohook + zh hook) ...")
    common.spawn_detached(cmd, log_file)
    print(f"[fgoa-wine] the game is starting on its own; live output: {log_file}")
    print("[fgoa-wine] the launcher stays responsive - press Stop Game to end the session.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
