#!/usr/bin/env python3
"""FGO_Launcher.ps1 — кнопка Play: подготовить игру и запустить её через inject.exe.

Лончер передаёт режим экрана и разрешение аргументами, а перед этим сам записывает колоду
в разделяемую память FGO_DECK_<sha256 пути App>. Имя канала игра узнаёт из переменной
FGO_DECK_CHANNEL — её ставит наш scripts/launch.py, формула взята из
FGOLocalPlatform/DeckReaderUI.Kancolle/GameCommunication.cs.

Наш процесс живёт столько же, сколько игра: лончер стримит наш вывод в панель логов, а
кнопка Stop Game убивает ago.exe / amdaemon.exe / inject.exe по имени.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402

ARG_MAP = (("-DisplayMode", "--mode"), ("-ResolutionWidth", "--width"),
           ("-ResolutionHeight", "--height"), ("-InputMode", "--input"),
           ("-TargetFps", "--fps"))


def main():
    argv = sys.argv[1:]
    common.log_call("FGO_Launcher", argv)
    # Оригинальный FGO_Launcher.ps1 сам поднимает сервер (autoStartLocalServer), иначе игра
    # не дойдёт до титульного экрана и покажет ERROR 4102.
    if not all(common.port_open(port) for port in (777, 9999, 7777)):
        print("[fgoa-wine] local server is not running - starting it")
        if common.run(["bash", common.script("server.sh")], timeout=240) != 0:
            print("[fgoa-wine] the local server did not start; expect ERROR 4102 in the game",
                  file=sys.stderr)
    cmd = ["python3", common.script("launch.py"), common.install_root(), "--run"]
    for flag, option in ARG_MAP:
        value = common.arg_value(argv, flag)
        if value:
            cmd += [option, value]
    print(f"[fgoa-wine] deck channel: {common.deck_channel()}")
    print("[fgoa-wine] starting the game (inject.exe + fgoglcompat + fgohook) ...")
    code = common.run(cmd)
    print(f"[fgoa-wine] the game process finished with exit code {code}")
    if code not in (0, 124):
        print(f"[fgoa-wine] exit code {code}: check logs/ next to App "
              f"(fgo-last-launch.log, ago-crash-*.dmp) and /tmp/ago*.log", file=sys.stderr)
    return code


if __name__ == "__main__":
    sys.exit(main())
