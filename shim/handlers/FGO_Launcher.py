#!/usr/bin/env python3
"""FGO_Launcher.ps1 - the Play button: prepare the game and start it through inject.exe.

The launcher reads our output into its log panel and only releases the button on EOF.
So the game is started detached (common.spawn_detached): its own log, its own session,
exit 0 right away - exactly like the original script, which backgrounds the game and
returns. Waiting for the game (as an earlier version did) leaves the button stuck for the
whole session: presses pile up and each one starts another instance - and another server.

Before starting we kill what is left of the previous session from this same install
(ago/amdaemon/inject) - what FGO_Launcher.ps1 does through Get-Process | Stop-Process.

The original script brings the server up itself (autoStartLocalServer); without it the
game never reaches the title screen and shows ERROR 4102.

Deck: the launcher publishes it into the shared memory FGO_DECK_<sha256 of the App path>;
the game learns the channel name from FGO_DECK_CHANNEL, which scripts/launch.py sets
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
    """Processes of this install's previous session. Under Wine they show up by exe name."""
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
