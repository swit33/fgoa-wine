# Internals — how this glue works

Companion to `README.md`. Everything here is about *how* it works and *why* each change exists;
read that file first if you only want to install and play.

---

## What the shipped platform expects, and what Wine gives it

The front end (`FGOAC scooby.exe`) is a Windows-only .NET/WPF program that drives every action
through PowerShell. Wine's PowerShell 7 starts but executes nothing (both 7.2 and 7.4: the .NET host
comes up, the managed assembly "exits 0", no command runs), so on Linux the launcher cannot do
anything by itself.

Wine itself has no trouble with non-PE targets (a `#!` script named `pwsh.exe` runs fine), but the
launcher starts its scripts with a handle list (`STARTUPINFOEX`), and for that shape Wine reports a
child that exits 0 **without ever running the file**. The version probe, which uses a plainer
`ProcessStartInfo`, was unaffected — which is what made this confusing at first: the probe worked,
every button did nothing.

So `pwsh.exe` is replaced by a shim with two pieces:

| Piece | What it does |
| --- | --- |
| `shim/stub/pwsh-stub.c` | The PE that goes in the prefix at `C:\Program Files\PowerShell\7\pwsh.exe`. It does one thing: `CreateProcess` the bash shim with the same arguments and the same std handles, wait, and return its exit code. `shim/stub/build.sh` builds it with `winegcc --target=x86_64-windows` (Wine's own headers and import libraries — no mingw needed). The real PowerShell is kept as `pwsh.real.exe`, and `pwsh-stub.ini` beside it holds the shim's path. |
| `shim/pwsh-shim.sh` | The dispatcher: logs every invocation to `/tmp/fgoa-shim.log`, recognises the probe and the eight script names, and hands over to a handler. Anything unknown is logged and **fails loudly** instead of pretending to succeed — that is how a launcher update that calls something new gets noticed. It runs handlers with `python3 -u`, so their output reaches the launcher's log panel as it happens. |
| `shim/handlers/*.py` | One handler per call site. They reuse `scripts/`, return the exit codes the launcher expects (0, 2, 4, 5, 7, 9, 10, 11, 13), print progress lines for its log panel, and never keep the launcher's pipes open. |

The nine call sites in the launcher's C#: the version probe, the writable-layout check, the
environment report, `Apply-EN-Patch.ps1`, `Start-FGOLocalServer.ps1`, `Stop-FGOLocalServer.ps1`,
`Stop-FGOLocalServerWhenIdle.ps1`, `FGO_Launcher.ps1`, and its updater.

Testing trap: while any modal dialog of the launcher is open, its main window is
`IsWindowEnabled == False` and silently ignores every click. Dismiss the dialog first.
For automating the window from outside, note that a Wayland compositor will not deliver synthetic
clicks into it; under X11 `xdotool` works, under Wayland the click would have to be produced from
inside Wine (`SetCursorPos` + `mouse_event` from the platform's own python). Nothing in this project
needs that: the cabinet-role cure in `UPSTREAM.md` is a key the player presses.

---

## Why each patch exists

* **`inject.exe` + hooks** — the game is an arcade title driven by SEGATOOLS. `fgohook.dll` is the
  platform's file/network hook (it redirects `192.168.100.1:*` to `127.0.0.1:*` and hosts the
  English layer), `fgoglcompat.dll` translates the NVIDIA-only OpenGL extensions (it aliases 18
  bindless-texture entry points) onto the ARB ones Mesa provides. Both are injected before `ago.exe`;
  `launch.py` does exactly that.

* **`USER32.SetWindowFeedbackSetting` import rename** — `ago.exe` calls it at window creation. Wine
  declares it as an unimplemented stub and *aborts the process* when it is called. Renaming the
  import to `IsWindow` (same signature: takes a window handle, does nothing, returns a BOOL) keeps
  the call harmless; only 24 bytes of the import name table change. `patch-ago-import.py` does it,
  and `install.sh` always rebuilds `ago.exe` from `App/ago.exe.pristine`, so the result is
  deterministic.

* **Robust-access context flag (`patch-ago-gl.py`)** — at startup the game creates a second OpenGL
  context asking for `WGL_CONTEXT_FLAGS_ARB = ROBUST_ACCESS`. Wine's EGL backend refuses that request
  (`EGL_BAD_MATCH`), the game drops the context and then resolves its 280-entry OpenGL table with none
  current — and Wine's `wglGetProcAddress` returns NULL for every GL 1.2+ symbol in that state, so the
  table stays zero and the game dies on the first call through it. Zeroing the attribute name at
  `0x27AF7D` ends the attribute list before the flag is read, so the context exists at all. On this
  project's AMD + Mesa hardware Mesa answers the request instead of refusing it, so the crash does not
  happen here and the patch is carried unverified — see the script's own header and
  `docs/UPSTREAM.md`.

* **Cabinet network `192.168.100.0/24` on `lo`** — the platform's own network plan
  (`App/FGO_LocalNetwork.ps1`: `Server = 192.168.100.1`, `Cabinet = 192.168.100.11`) is what the game is
  told to expect, and `launch.py` writes it into the config the game reads. On Windows the platform
  creates that network itself; under Wine nothing does. `fgohook.dll` rewrites the session traffic to
  `127.0.0.1`, which is why the game plays without the addresses — but the platform probe at boot has
  no such help, and a cabinet that cannot reach the location server comes up as a *sub* unit and shows
  `ERROR 8404`. `install.sh` puts both addresses on `lo` and keeps them across reboots
  (`fgoa-cabinet-net.service`); `launch.py` warns when they are missing.

* **Wine backend: X11 by default** — Wine takes its Wayland driver whenever `WAYLAND_DISPLAY` is set,
  and X11/XWayland is the path everything here was verified on, so `scripts/launcher.sh` and
  `scripts/launch.py` clear the variable unless `FGOA_WINE_BACKEND="wayland"` (what
  `install.sh --use-wayland` writes). Measured on the machine this was built on (Wine 11.17,
  CachyOS, RX 9070 XT): the launcher loads `winex11.so` with `WAYLAND_DISPLAY` set, with it empty, with
  `WINEDLLOVERRIDES=winewayland.drv=b` and with `HKCU\Software\Wine\Drivers\Graphics=wayland` — so on
  this build the Wayland driver is never selected and the backend flag changes nothing here. What the
  X11 path does give is a working input chain for both windows (verified: launcher panes react to
  clicks, the game's title answers a click with `pre_start` carrying the card from `DEVICE/aime.txt`).
  Note what is *not* part of this: two crashes were chased as "lost clicks" before, and neither was a
  driver problem — one was a modal dialog swallowing clicks by design (the launcher disables its main
  window while one is open), the other is that synthetic clicks from the compositor (Hyprland's
  dispatchers, XTest through XWayland) never reach a Wine window at all. Real input does.

* **`config/drirc.d/99-fgoa.conf`** — with default Mesa settings the game's shader compilation fails
  with `embedded structure declarations are not allowed` and the game crashes. Mesa ships the matching
  switch (`allow_glsl_embedded_structure_declarations`); the config enables it for `ago.exe` only.
  `launch.py` points `DRIRC_CONFIGDIR` at this folder, so the system config is not touched (the
  installer also symlinks it into `/usr/share/drirc.d` for launches that skip our scripts).

* **Privileged port 777** — the game always connects to `127.0.0.1:777` for ALL.Net: the hook
  rewrites the address, not the port, and the game ignores `[dns] startupPort`. On Linux ports below
  1024 need privileges, so `net.ipv4.ip_unprivileged_port_start` is raised to 777 (not to 0: only the
  one port is needed).

* **Database port** — the platform's default is 8888. If something else holds it (`docker-proxy`, as
  on the machine this was built on), `set-ports.py` moves the server's ports consistently through the
  platform's own config tool (`core.yaml`, `fgo-launcher.json`, `segatools.ini`, `mariadb.ini`).

* **English: the `zh` hook, patched to load** — see `UPSTREAM.md` for where the fix came from.
  `fgozh.dll` hooks five `ntdll` functions, one of them `NtQueryInformationByName`, which Wine does
  not export; the hook treats the missing export as fatal (`MH_ERROR_FUNCTION_NOT_FOUND`) and bails
  out of `DllMain`, after which `inject.exe` kills the launch. Five bytes at offset `0x19E99`
  (`mov eax,0Ch` → `xor eax,eax`) make it carry on, and the hook then does its job:
  `logs/fgozh.log` reports `REDIRECT_INDEX files=1683`.

  The same dataset is *also* laid down on disk, because the hook needs `App/zh/` present anyway and
  because it is the fallback when a future build breaks the five-byte signature (`apply-en.py` then
  warns, skips the hook, and the game still shows English):

  * **1683 files** — `App/zh/text-outputs.json` (1443) plus the 240 rebuilt sprite archives in
    `App/zh/rom/sprite/` (they are not in that list; without them the Aime registration, summon and
    result screens stay Japanese artwork) = exactly the `1683` the hook reports as `REDIRECT_INDEX`.
    `App/zh/rom/font/` is deliberately **not** copied: that font belongs to Cloud23333's Chinese set
    and the hook does not redirect it either.
  * **2224 strings** in `ago.exe` — offsets and text from `App/zh/executable-text.json`. 550 entries
    carry an **empty** translation (among them GLSL shader sources) and are skipped, exactly as the
    hook skips them; writing them out would hang the game at startup.
  * payload copy: `payload/**` from the scooby release is copied over the install and verified
    against `manifest.json`, which is what the original `Apply-EN-Patch.ps1` does too.
  * backups: replaced files under `_en-overlay-backup/`, `App/ago.exe.en-overlay.bak`,
    `App/zh/fgozh.dll.wine-hook.bak`.

* **Server-side fixes** — `patch-server.py` applies two text patches from `yana-arch`: the account
  CLI no longer prints INFO logs in front of its JSON (the launcher showed
  `bad_output: [INFO] … {json}` on the Account page), and the servant-upgrade tables are indexed once
  instead of being rescanned per Servant. Both are idempotent and verified by their own `--verify`.

* **Cabinet role** — the game's startup mode decides whether it is a main or a sub cabinet, and it
  lives in `GameData/SDEJ/amdaemon_aux.json` (`lan_install.server`). A fresh install boots as
  *Satellite (Sub Unit)*, waits forever for a Location Server that an offline setup does not have,
  and then dies with **ERROR 8404**. `launch.py` passes `cabinetMode` through as `-sm` like the
  original script does, but that does **not** change the saved mode — only the game's own test menu
  does (README, "If the game shows ERROR 8404"). See `UPSTREAM.md` for the test-menu route that was
  verified here.

---

## Layout and environment

The game root holds the platform's files plus `fgoa-wine/` (this folder). Inside it:

```
install.sh, uninstall.sh, README.md, docs/
config/drirc.d/99-fgoa.conf        Mesa config for ago.exe
scripts/                           launcher.sh, play.sh, server.sh, launch.py,
                                   apply-en.py, patch-ago-import.py, patch-server.py,
                                   set-ports.py, fix-account.py, stop-watcher.py
shim/                              pwsh-shim.sh, stub/, handlers/
fonts/                             font mapping the installer applies from your system
```

Environment: `FGOA_ROOT` (game root, default: the folder above `fgoa-wine`), `WINEPREFIX` (default
`~/.local/share/fgoa-wine/prefix`), `FGOA_SCRIPTS`, `FGOA_HANDLERS`, `FGOA_SHIM_LOG`
(default `/tmp/fgoa-shim.log`). `install.sh` writes them into `~/.config/fgoa-wine/config.env`, which
the shim, the handlers and the `scripts/*.sh` wrappers read.

`launch.py` sets, for the game process: `SEGATOOLS_CONFIG_PATH` (the runtime INI it generates),
`FGO_INSTALL_ROOT`, `FGO_TARGET_FPS`, `FGO_LOCAL_NETWORK`, `FGO_LOCAL_{HTTP,BILLING,AIME}_PORT`,
`FGO_PRINT_METADATA_ONLY`, `FGO_ZH_ENABLED` (1 when the hook is patched), `FGO_DECK_CHANNEL`,
`DRIRC_CONFIGDIR`, and for borderless mode `__COMPAT_LAYER=DISABLEDXMAXIMIZEDWINDOWEDMODE` +
`FGO_BORDERLESS_COMPOSED=1`. The deck channel name is
`FGODeck_<sha256hex(upper(path of App))>` — the formula from the launcher's
`GameCommunication.cs`, which also creates the matching shared memory and mutex.

Logs worth reading when something breaks: `/tmp/fgoa-shim.log` (every launcher call),
`logs/fgo-launch-<date>.log` (the game's live output from a Play), `/tmp/mariadb.log`,
`/tmp/artemis.log`, and the game's own `logs/` next to `App/` (`fgozh.log`, `fgo.log`, `aimedb.log`,
`ago-crash-*.dmp`).

---

## Assembling the game folder

The installer expects the game folder to exist already; this is how such a folder is put together
(reference for reproducing an install, not something the installer does):

1. **`本体`** — Cloud23333's platform, `FGOA_Cloud23333.part1..5.rar`, unpacked into the game root.
   Google Drive renames the parts it hands out (`part1-003.rar` and so on); `unrar` matches volumes by
   name, so they have to be linked or renamed back to `partN.rar` first. `part5` sometimes arrives
   inside the `V1.00` zip instead. The archive password used for this build was
   `bilibili Cloud23333`.
2. **`前端`** — his update. `V1.01…zip` / `V1.02…zip` each contain `.rar` parts; unpack the zip
   somewhere temporary and then unpack `*part1.rar` over the same game root. **1.02 is cumulative**,
   so applying 1.01 first is optional; either way the result must contain `App/FGO_Runtime.dll`,
   which is how the installer recognises that an update was applied.
3. **The scooby release** — `FGOAC-scooby-v1.1.2.zip` unpacked over the same root: it brings
   `FGOAC scooby.exe`, `payload/`, `manifest.json`, `Apply-EN-Patch.ps1`, `compat/`, the guides.

The three stages all write into the same folder, later stages overwriting earlier files. A tree built
that way is what `install.sh` calls "the game folder"; nothing after step 3 cares where the archives
came from.

It also helps to unpack each archive *separately* somewhere of its own (`本体/`, `前端-V1.01/`,
`前端-V1.02/`, `FGOAC-scooby-v1.1.2/`): then its contents can be inspected and compared with what a
given install ended up with, and a fresh game folder can be assembled from the pieces by hand.
