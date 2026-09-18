# FGO Arcade on Linux — Wine/Proton runner

A small set of scripts that run **Fate/Grand Order Arcade** (the "FGO Arcade local platform" by
**Cloud23333**) on Linux under Wine, together with the English patch
[**FGOAC scooby**](https://github.com/githubuser420x/FGOAC-scooby).

Nothing here is a game download. This folder holds only the glue that the shipped front end cannot
provide on Linux: the shipping launcher is a Windows-only .NET/WPF program that drives every action
through PowerShell, and PowerShell does not run under Wine (both 7.2 and 7.4 start and then execute
nothing). These scripts do the same work directly — generate the game's runtime INI, start the local
server, apply the English dataset, and launch the game through the injector with the right hooks.

**Install:** drop this folder into the folder where the game should live, put Cloud23333's archives and
the FGOAC scooby release zip somewhere the installer can find them (its own folder, the game folder,
the parent, `~/Downloads`, or `--sources <dir>`), then run `./install.sh`. It unpacks everything,
applies the translation, creates the Wine prefix and sets up the shim, fonts and ports.

This folder is also a git repository, kept *outside* the game (so wiping the game cannot take the
source with it). To deploy a build, copy it in and run the installer from there:

```bash
cp -a fgoa-wine /path/to/game/ && /path/to/game/fgoa-wine/install.sh --sources /path/with/archives
```

---

## Contents

| Path | What it is |
| --- | --- |
| `install.sh` | **The installer.** Finds the archives, unpacks the game + patches + launcher release, applies the English layer, creates and prepares the Wine prefix, fixes the ports, then verifies everything. `--verify` checks an existing install, `--sysctl` also fixes the privileged-port setting. |
| `uninstall.sh` | Removes our layer from the prefix (shim, fonts, their registry entries) and puts the real PowerShell back. Never touches the game or its data. |
| `config/drirc.d/99-fgoa.conf` | Mesa config: `allow_glsl_embedded_structure_declarations` for `ago.exe`. The game's shaders use nested `struct` declarations, which NVIDIA's compiler accepts and Mesa rejects by default. `install.sh` adds symlinks to `/usr/share/drirc.d` beside it. |
| `scripts/launcher.sh` | **Starts the shipping launcher** (`FGOAC scooby.exe`) — the normal way to play. |
| `scripts/play.sh` | Starts the game directly, without the launcher. Screen mode, resolution, input and FPS come from `App/fgo-launcher.json`. |
| `scripts/launch.py` | The actual launcher: regenerates `DEVICE/runtime/segatools.runtime.ini` the way `App/FGO_Launcher.ps1` does, then runs `inject.exe` with the GL and file hooks. |
| `scripts/server.sh` | **Starts/stops the local server**: bundled MariaDB + ARTEMiS (ALL.Net 777, billing 9999, AimeDB 7777, DB 8889). `./server.sh stop` stops both. |
| `scripts/apply-en.py` | **Applies the English dataset** to the install: patches `App/zh/fgozh.dll` so the release's own English hook loads under Wine, copies the 1683 override files and rewrites the translated strings inside `ago.exe`. Idempotent; keeps backups. |
| `scripts/patch-server.py` | Two text fixes in `Server/tools/` taken from [yana-arch/FGOAC-scooby-linux](https://github.com/yana-arch/FGOAC-scooby-linux) (branch `linux-support`, applied verbatim): the account CLI no longer prints INFO logs in front of its JSON (the launcher showed `bad_output` on the Account page), and the servant-upgrade tables are indexed once instead of being rescanned per Servant. Idempotent, `--verify` included. |
| `scripts/patch-ago-import.py` | One-line, one-time binary fix in `ago.exe`: renames the imported `USER32.SetWindowFeedbackSetting` (an unimplemented Wine stub that aborts the process) to a harmless existing export. |
| `scripts/set-ports.py` | Moves the local server's ports using the platform's own config tool (`Server/tools/fgo_server_config.py`), with its "server is running" guard disabled. `install.sh` calls it when the DB port 8888 is already taken. |
| `scripts/fix-account.py` | Repairs an install where the game created the "unbound" account `aime_id 4294967295` before a real account existed (the launcher then throws on it). `install.sh` does not call this by itself — the rule is: create the account in the launcher *before* the first game start. |
| `tools/win-click.py` | Clicks, moves the mouse and sends keys inside a Wine window (`SetCursorPos` + `mouse_event` + `keybd_event`, coordinates relative to the window's client area). Hyprland's dispatchers and `wtype` do **not** reach WPF or an XWayland game window. For debugging the UI. |

Environment: `FGOA_ROOT` (game root, default: the folder above `fgoa-wine`), `FGOA_PREFIX` (Wine
prefix, default `~/.local/share/fgoa-wine/prefix`) and `WINEPREFIX` (takes precedence if set).
`install.sh` writes both into `~/.config/fgoa-wine/config.env`, which the shim and the handlers read.

---

## The launcher: how it works without PowerShell

The shipping front end (`FGOAC scooby.exe`) drives every action through PowerShell: it starts a
`pwsh.exe` process for each of nine calls (nine call sites in its C# — the version probe, the
writable-layout check, the environment report, `Apply-EN-Patch.ps1`, `Start-FGOLocalServer.ps1`,
`Stop-FGOLocalServer.ps1`, `Stop-FGOLocalServerWhenIdle.ps1`, `FGO_Launcher.ps1`, and the updater).
PowerShell 7 under Wine starts but executes nothing (both 7.2 and 7.4: the .NET host comes up, the
managed assembly "exits 0", no command runs), so the launcher cannot do anything on Linux. Wine
itself has no trouble with non-PE targets — a `#!` script named `pwsh.exe` runs fine — but the
launcher starts its scripts with a handle list (`STARTUPINFOEX`), and for that shape Wine reports a
child that exits 0 **without ever running the file**. The version probe, which uses a plainer
`ProcessStartInfo`, was unaffected — which is what made this so confusing at first.

| Piece | What it does |
| --- | --- |
| `install.sh` | Builds the PE stub if needed and installs it at `C:\Program Files\PowerShell\7\pwsh.exe`, writing `pwsh-stub.ini` beside it with the path of the bash shim (the real PowerShell is kept as `pwsh.real.exe`), installs the WPF fonts **and registers them in the prefix registry** (without the registry entries the launcher still dies in `TypefaceMap.MapUnresolvedCharacters`), writes `~/.config/fgoa-wine/config.env`, and can apply the port-777 sysctl (`--sysctl`) and create a proper account (`--fix-account`). `./uninstall.sh` reverses it. |
| `shim/stub/pwsh-stub.c` | The PE that goes in the prefix. It does one thing: `CreateProcess` the bash shim with the same arguments and the same std handles, wait for it, and return its exit code. `shim/stub/build.sh` builds it with `winegcc --target=x86_64-windows` (Wine's own headers and import libraries — no mingw needed). |
| `shim/pwsh-shim.sh` | The dispatcher, a bash script: logs every invocation (`/tmp/fgoa-shim.log`), recognises the probe and the seven scripts by name, and hands over to a handler. Anything unknown is logged and fails loudly instead of pretending to succeed — that is how you notice a launcher update that calls something new. |
| `shim/handlers/*.py` | One handler per call. They reuse the scripts in `scripts/`, return the exit codes the launcher expects (0, 2, 4, 5, 7, 9, 10), print progress lines for its log panel, and never hold the launcher's pipes open. |
| `tools/win-click.py` | Clicks and moves the mouse inside a Wine window from Windows (`SetCursorPos` + `mouse_event`, coordinates relative to the window's client area). Hyprland's own `send_shortcut` does **not** reach WPF, and `wtype` does not reach an XWayland game window at all. |

Trap worth knowing when testing the UI: while any modal dialog of the launcher is open, its main
window is `IsWindowEnabled == False` and silently ignores every click (`tools/win-click.py` finds it
by title, `FGOAC scooby` is the main window — dialogs carry their own titles). Dismiss the dialog
first. Also note the launcher writes its own runtime lines only into its log panel
(bottom right, “Show logs”).

## Install

You need four downloads (none of them ship here): Cloud23333's platform `本体`, his `前端` 1.01 and
1.02 updates, and the **FGOAC scooby** release zip. Put them anywhere `install.sh` can see — its own
folder, the game folder, the parent, `~/Downloads` — or point at them with `--sources <dir>`.

```bash
# this folder sits where the game should live, as <game root>/fgoa-wine
./install.sh                     # or: ./install.sh --root /path/to/game --sysctl
./install.sh --verify            # later: check that everything is still in place
```

What it does, in order:

1. Finds the archives. `本体` parts may still carry Google Drive's rename (`part1-003.rar`): the
   installer links them back to canonical names in a temp folder, because `unrar` matches volumes by
   name. A missing `part5.rar` is taken out of the `V1.00` zip.
2. Unpacks `本体` into the game root (27 637 035 202 bytes, 56 353 files), then `前端` 1.01, then
   1.02 (cumulative), then the FGOAC scooby release over the same root.
3. Checks the files the platform needs (`App/ago.exe`, `App/inject.exe`, `AMFS/ICF1`, the bundled
   Python and MariaDB, `Server/tools/fgo_account.py`, and so on).
4. Applies our layer: keeps a pristine `App/ago.exe.pristine`, then rebuilds `ago.exe` from it — the
   `USER32.SetWindowFeedbackSetting` import rename, then the English strings — patches
   `App/zh/fgozh.dll` so the release's own English hook loads, overlays the 1683 English resource
   files, and fixes the two server-side tools. Re-running is deterministic because it always starts
   from the pristine copy and every step is idempotent.
5. Creates the Wine prefix if needed and prepares it: the shim at
   `C:\Program Files\PowerShell\7\pwsh.exe`, the WPF fonts **and their registry entries**, and
   `~/.config/fgoa-wine/config.env`.
6. Sets up the ports: warns (or with `--sysctl` fixes) the privileged 777 for ALL.Net, and picks a
   free database port if 8888 is taken (on this machine a Docker container holds it, hence 8889).
7. Verifies the result and prints what to do next.

Then, day to day:

```bash
./scripts/launcher.sh        # the shipping launcher — the normal way to play
./scripts/server.sh stop     # stop the local server when finished
./scripts/play.sh            # start the game directly, without the launcher
```

**Before the first game start, create an account** in the launcher (Account → New Account). If the game
starts first with an empty `DEVICE/aime.txt`, it creates an account with `aime_id 4294967295`, which the
launcher cannot parse — that is what `scripts/fix-account.py` exists for. `scripts/launch.py` also
defends against it: if the card file is empty while the profile already holds an account with a valid
id, it writes that account's access code before starting, so Play works even when the account was never
explicitly selected. That said, the launcher's own Account page is the right place to make the choice.

### Manual install (what the installer automates)

```bash
unrar x -o+ -p'<password>' FGOA_Cloud23333.part1.rar  <root>/     # after renaming the parts
unzip -o V1.01-*.zip -d /tmp/fe101 && unrar x -o+ -p'<password>' /tmp/fe101/V1.01/*part1.rar <root>/
unzip -o V1.02-*.zip -d /tmp/fe102 && unrar x -o+ -p'<password>' /tmp/fe102/V1.02/*part1.rar <root>/
unzip -o FGOAC-scooby-v*.zip -d <root>/
./scripts/patch-ago-import.py <root>/App/ago.exe SetWindowFeedbackSetting IsWindow --apply
./scripts/apply-en.py <root> --apply
```

---

## Why each patch exists

* **`inject.exe` + hooks** — the game is an arcade title driven by SEGATOOLS. `fgohook.dll` is the
  platform's file/network hook (it redirects `192.168.100.1:*` to `127.0.0.1:*` and hosts the English
  layer), `fgoglcompat.dll` translates the NVIDIA-only OpenGL extensions the game asks for onto the
  ARB ones Mesa provides (it aliases 18 bindless-texture entry points). Both must be injected before
  `ago.exe`; the launcher script does exactly that.

* **`SetWindowFeedbackSetting` import rename** — `ago.exe` calls it at window creation. Wine declares
  it as an unimplemented stub and *aborts the process* when it is called, which kills the game at
  startup. Renaming the import to `IsWindow` (same signature: takes the window handle, does nothing,
  returns a BOOL) keeps the call harmless. Only 24 bytes of the import name table change.

* **`drirc.d`** — with the default Mesa settings the game's shader compilation fails with
  `embedded structure declarations are not allowed`, and the game then crashes. Mesa ships the
  matching switch (`allow_glsl_embedded_structure_declarations`); the config enables it for
  `ago.exe` only. `DRIRC_CONFIGDIR` points the driver at this folder, so the system config is not
  touched.

* **Privileged port 777** — the game always connects to `127.0.0.1:777` for ALL.Net: the hook
  rewrites the address, not the port, and the game ignores `[dns] startupPort`. On Linux ports below
  1024 need privileges, so allow them from 777 up:

  ```bash
  echo 'net.ipv4.ip_unprivileged_port_start = 777' | sudo tee /etc/sysctl.d/99-fgoa-ports.conf
  sudo sysctl -w net.ipv4.ip_unprivileged_port_start=777
  ```

* **Database port 8889** — the platform's default is 8888. If something else on the machine already
  holds 8888 (`docker-proxy`, as here), run `scripts/set-ports.py` to move the server's ports
  consistently (it edits `core.yaml`, `fgo-launcher.json`, `segatools.ini` and `mariadb.ini`).

* **English: the `zh` hook, patched to load** — the English release works by injecting
  `App/zh/fgozh.dll`, which redirects game resources to `App/zh/` and patches the translated strings
  inside `ago.exe` in memory. Under Wine that DLL loaded, logged its index and then failed its own
  `DllMain`, which makes the injector kill the launch. The cause, and the fix, come from
  [yana-arch/FGOAC-scooby-linux](https://github.com/yana-arch/FGOAC-scooby-linux): `fgozh.dll` hooks
  five `ntdll` functions, one of them `NtQueryInformationByName`, which Wine does not export; the
  hook treats the missing export as fatal (`MH_ERROR_FUNCTION_NOT_FOUND`) and bails out. Five bytes at
  offset `0x19E99` (`mov eax,0Ch` → `xor eax,eax`) make it carry on, and the hook then does its job:
  `logs/fgozh.log` reports `REDIRECT_INDEX files=1683` and the game is translated the way the author
  intended. `apply-en.py` applies that patch (after verifying the bytes, keeping
  `App/zh/fgozh.dll.wine-hook.bak`), and `launch.py` injects the hook with `FGO_ZH_ENABLED=1`.

  The same dataset is *also* laid down **on disk**, because the hook needs `App/zh/` present anyway
  and because it is the fallback when a future build breaks the five-byte signature: `apply-en.py`
  then warns and skips the hook, and the game still shows English.

  * **1683 files** — `App/zh/text-outputs.json` (1443) plus the 240 rebuilt sprite archives in
    `App/zh/rom/sprite/` (they are not in that list; without them the Aime registration, summon and
    result screens stay Japanese artwork) = exactly the `1683` the hook reports as `REDIRECT_INDEX`.
    `App/zh/rom/font/` is deliberately **not** copied: that font belongs to Cloud23333's Chinese set
    and the hook does not redirect it either.
  * **2224 strings** in `ago.exe` — offsets and text from `App/zh/executable-text.json`. 550 entries
    carry an **empty** translation (among them GLSL shader sources) and are skipped, exactly as the
    hook skips them; writing them out would hang the game at startup.

  Backups: replaced files under `_en-overlay-backup/`, `App/ago.exe.en-overlay.bak`. The pristine
  `ago.exe` from `本体` can also be re-extracted from the RAR archives.

* **Graphics on non-NVIDIA cards** — the game asks the driver for NVIDIA-only OpenGL extensions
  (`GL_NV_bindless_texture` and friends). Two community layers answer that on AMD/Intel, and the
  launcher's compat folder (shipped in the scooby release as `compat/`) can install either from its
  Display page:
  * `compat/fgoglcompat.dll` — the older, wider one: RX 500/6000/7600 and desktop Ryzen graphics.
    This is what `launch.py` injects here, and what this install was verified with.
  * `compat/amd-shim/opengl32.dll` — fluphus's newer shim (MIT), installed as `App/opengl32.dll`
    with `App/opengl32real.dll` and `App/amdcfg/amdOglpSettings.cfg`. Published as tested only on an
    RX 7900 XTX; reported to fail at the first battle on RX 500/6000/7600. Untested on the RX 9070 XT
    this was developed on.
  NVIDIA users should ignore both and use PRIME render offload instead.

* **Running under Proton/UMU instead of plain Wine** — the launcher is a self-contained single-file
  .NET app; `DOTNET_BUNDLE_EXTRACT_BASE_DIR=C:\dotnet_bundle_extract` keeps its extraction in a
  predictable place and avoids startup hangs under Proton. For gamepads also set
  `WINEDLLOVERRIDES=xinput1_4=n,b`. Neither is needed with the `wine` this install uses.

* **The launcher's own compat switch** — `App/fgo-launcher.json` carries `gpuCompat: true`; the
  Display page can install a layer from `compat/` into `App/`. Do not enable it *and* keep our
  injected `fgoglcompat.dll` at the same time — pick one layer, not both.

---

## Screen mode, resolution, draw rates

* **Screen mode** — `App/fgo-launcher.json`: `displayMode` (`windowed` / `borderless` / `exclusive`),
  `resolutionWidth`/`resolutionHeight`, `inputMode`, `targetFps`. `launch.py` turns that into
  `[gfx]`/`[amvideo]` in the runtime INI and into the engine's native mode argument
  (`-hdtv720`, `-hdtv1080`, `-wqhd`, `-wuxga`, `-wqxga`), plus the borderless compatibility variables.
  Current setting: borderless 2560x1440. Edit the JSON and restart the game.
  Note: the file still carries `monitorDevice: "\\\\.\\DISPLAY5"` and window coordinates from the
  author's machine; the game falls back to the primary display, so it is harmless.

* **Draw rates (the gacha)** — `Server/artemis/config/fgo_summon_weights.json`, editable from the
  launcher: **Cards and Deck → the “Draw Rates” tab**. Every card has a `Weight (integer)` column with
  a live `Draw Chance` beside it (`weight / total weight`); the buttons above the table
  (`Even for All`, `Only Selected (100%)`, `Even for Selected`, `Exclude Selected`) work on the rows
  you select, and `Save - Applies to the Next Draw` writes the file. The server reads the weights at
  draw time, so **no restart is needed**. Presets can be saved, loaded, exported and imported
  (`Presets` + `Save as / Load / Export / Import / Open folder`).
  As shipped **every weight is 0 except one card**, so every summon returns the same Servant (Saber) —
  a config value, not a bug; `Even for All` gives every card the same chance. Candidates and their
  rarities are in `Server/artemis/titles/fgo/data/summon_candidates.json`, and the weights file is
  keyed by the **Card ID** shown in that table (the same `tc_id` the server uses).

---

## State of things

Working: the game boots, renders and is playable (verified: title, Aime registration, tutorial summon,
battle screens); English text and artwork; the local server answers ALL.Net and billing; the account
appears in `Server/state/fgo-players.json`.

Known issues:

* **The shipped front end** now works under Wine through the shim (`./install.sh`): the main window,
  Play, Start/Stop server, Account, Cards and Deck, Settings and Advanced pages, and its own
  “Check for updates”. Its buttons still need one human click each for the flows that start
  something long (Play takes the screen and boots the game for about a minute).
* **AimeDB** (`:7777`) accepts the game's connection but fails to parse it
  (`Failed to decrypt 0a because Data must be aligned to block boundary in ECB mode`) — the card
  reader protocol. Account creation and play are unaffected.
* **MariaDB must be stopped through the scripts.** `./scripts/server.sh stop` shuts the database down
the way Cloud23333's own stop script does — `mariadb-admin --no-defaults --user=root
--password=FgoLocalRoot2026 shutdown` — because the game's `mariadb.ini` points the client at the
non-root user and `skip-name-resolve`, which the client is not allowed to shut down with. Killing
`mariadbd.exe` leaves InnoDB to recover and the *next* start can crash under Wine with a “serious
error” dialog (that dialog is system-modal: while it is up, nothing else in the prefix reacts).
Player progress lives in the JSON profile, not in the database, so the game keeps working without
it — but anything written while the DB is down (summons, ownership) is lost.
* **Never let the game create the first account on its own.** If the game starts with an empty
  `DEVICE/aime.txt`, it creates an account with `aime_id = 4294967295`; the launcher parses `aime_id`
  as `int32`, throws in `RefreshAccountsAsync` and then re-opens the error dialog on a timer, which
ties the launcher in knots. `install.sh --fix-account` creates a normal account, points
`DEVICE/aime.txt` at it and removes the broken profile entry (with a backup); do it *before* the
first game start, or create the account from the launcher's Account page.
* The English dataset covers menus, story, tutorial, shops and the rebuilt artwork; a few event
  screens (co-op banners, co-op results, later event shops) remain Japanese artwork by design of the
  patch author.
* **`AimeDB`/servant upgrades**: the two `Server/tools/` fixes from `yana-arch` are applied; the
  "Max All Servants" timeout they describe did not reproduce here (7.6 s either way on a 120-servant
  profile), so the indexing fix is carried for portability, not because it was needed.
* Not done yet: a Faugus/Proton entry (the scripts currently run the prefix directly with `wine`).

Logs worth reading when something breaks: `/tmp/mariadb.log`, `/tmp/artemis.log`, the launcher
output, and the game's own `logs/` next to `App/` (`fgozh.log`, `*-trace.log`, `mariadb.log`).

---

## Credits

**Cloud23333** — the FGO Arcade local platform (server package, Chinese front end, file hook).
**githubuser420x** — the FGOAC scooby English patch and its launcher.
**yana-arch** — [FGOAC-scooby-linux](https://github.com/yana-arch/FGOAC-scooby-linux) (branch
`linux-support`): the five-byte `fgozh.dll` fix that brought the release's own English hook back to
life on Wine, and the two `Server/tools/` fixes (account CLI log level, servant-upgrade indexing),
both carried over here verbatim.
**fluphus** — the AMD/Intel OpenGL compatibility layer (MIT), shipped inside the platform.

Fate/Grand Order Arcade is SEGA's and TYPE-MOON's. Nothing in this folder contains game data or is
sold; it is glue for a fan translation applied to files you already have.
