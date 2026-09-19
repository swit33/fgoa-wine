# Upstream, prior art, and where each fix came from

This glue was written against two upstream projects and one community kit. This file records what
came from where, so a future maintainer can retrace every change instead of guessing.

## The pieces

| Piece | Author | Notes |
| --- | --- | --- |
| FGO Arcade local platform (`本体`, `前端`) | **Cloud23333** | The server package, the Chinese front end and the file hook. V1.02 is the one to be on. |
| FGOAC scooby (English patch + launcher) | **[githubuser420x](https://github.com/githubuser420x)** ([FGOAC-scooby](https://github.com/githubuser420x/FGOAC-scooby)) | `FGOAC scooby.exe`, `payload/`, `manifest.json`, `Apply-EN-Patch.ps1`, `GUIDE_EN.md`, and the compat layers in `compat/`. |
| `compat/fgoglcompat.dll` | arrived through the community | Aliases 18 NVIDIA-only OpenGL entry points onto ARB. Shipped as received, no licence file. |
| `compat/amd-shim/opengl32.dll` | **[fluphus](https://github.com/fluphus)** ([fgo-arcade-amd-shim](https://github.com/fluphus/fgo-arcade-amd-shim), MIT) | Newer AMD/Intel layer: an `opengl32.dll` forwarder plus `amdcfg/amdOglpSettings.cfg`. Published as tested only on an RX 7900 XTX; reported to fail at the first battle on RX 500/6000/7600. This install uses the older `fgoglcompat.dll` instead (injected by `launch.py`). NVIDIA cards want PRIME render offload, not either layer. |
| wine-compat | **[quinnjr](https://github.com/quinnjr)** ([FGOAC-scooby](https://github.com/quinnjr/FGOAC-scooby), branch `wine-compat`, MIT) | The X11 backend, the cabinet network addresses and the robust-access `ago.exe` patch came from here. Not a base for this project: he bypasses the launcher instead of running it. See the section below. |
| `FGOAC-scooby-linux` | **[yana-arch](https://github.com/yana-arch)** ([FGOAC-scooby-linux](https://github.com/yana-arch/FGOAC-scooby-linux), branch `linux-support`) | The prior Linux kit this project compared itself against. Three fixes were adopted from it — see below. |

## What came from yana-arch/FGOAC-scooby-linux

Their kit is a compat kit for the same release: a `linux/` folder (`ps_shim.py`, setup and network
scripts, a Lutris profile), an `overlay/` that is byte-identical upstream plus two patched server
tools, and docs. Their shim replaces `pwsh.exe` with a Python script carrying a shebang — which works,
because Wine does run shebang scripts, though not through the `.NET` handle-list path that the
launcher's buttons use (hence the PE stub here).

Adopted, verbatim in intent and verified here:

1. **The five-byte `fgozh.dll` fix.** Their diagnosis: `fgozh.dll` hooks five `ntdll` functions, one
   of them `NtQueryInformationByName`, which Wine does not export; the hook treats the missing export
   as fatal and returns FALSE from `DllMain`, so `inject.exe` kills the launch. Their patch:
   offset `0x19E99`, `b8 0c 00 00 00` → `31 c0 90 90 90`. Verified on this machine: the hook loads,
   `logs/fgozh.log` reports `REDIRECT_INDEX files=1683`, the game reaches the login. `apply-en.py`
   now applies it (with a byte check, a backup, and a fallback to the on-disk overlay if the
   signature ever stops matching).
2. **`Server/tools/fgo_account.py`** — one change: read `fgo.yaml` unconditionally, force
   `loglevel = "warning"`, and write a temporary `fgo.yaml` when the profile is not isolated;
   otherwise the CLI prints INFO logs in front of its JSON and the launcher shows
   `bad_output: [INFO] … {json}` on the Account page.
3. **`Server/tools/fgo_account_actions.py`** — index `mst_svt_limit`, `mst_svt_skill`,
   `mst_svt_support_skill` and `mst_svt_noble_phantasm` once with `defaultdict` instead of rescanning
   them per Servant. Their numbers: "Max All Servants" 81.85 s → 5.04 s, inside the launcher's
   60-second timeout. **On this machine the timeout did not reproduce** (7.6 s either way on a
   120-Servant profile), so the fix is carried for portability rather than need. The `lru_cache` they
   also added to `artemis/titles/fgo/index.py` was *not* taken: unnecessary here.

Both server patches are applied by `scripts/patch-server.py` (six textual rules, idempotent, with a
`--verify`); after patching, our copies of those two files are byte-identical to theirs.
`shim/handlers/Apply-EN-Patch.py` re-runs `patch-server.py` after the English layer, because the
payload copy would otherwise restore the pristine tools and undo the fixes.

Differences kept deliberately: this project needs one sysctl (port 777) where theirs needs
`ip_unprivileged_port_start=0` and `ptrace_scope=0` as well; it also needs no host `powershell`
package. Their `setup-fgoa-linux.sh` never installs `ps_shim.py` (the symlink it makes points
`powershell.exe` at the *host* `pwsh`, which cannot run `.exe` files) — here the installer wires the
shim itself.

Where we came round to their view: they put `192.168.100.1` on `lo` with a systemd unit, and for a
long time this project did not, because the game plays without it (`fgohook.dll` rewrites the session
traffic to `127.0.0.1`) and there was no 8404 in a session that had already worked. The cabinet role
sections below explain why that address is there after all. We add the platform's full pair
(`192.168.100.1/24` and `192.168.100.11/24`, see `App/FGO_LocalNetwork.ps1`) rather than one `/32`,
and keep it in `fgoa-cabinet-net.service` the same way they do.

## What came from quinnjr/FGOAC-scooby (branch `wine-compat`)

One commit (`f81dbe5`, MIT) that makes the *platform's own* game run under Wine, by a different route
than this project: his `patch/wine/play-fgo.sh` is the only entry point, it brings up MariaDB and
ARTEMiS, applies the patches and launches `ago.exe` with Zink — the launcher is not used at all, and
`src/FGOLocalPlatform/App.cs` is patched to write startup and UI errors into `logs\wine-startup.log`
because the dialog is not always visible under Wine. This project does the opposite: it makes the
shipped launcher work (PE stub + bash shim in place of `pwsh.exe`) so the GUI, the deck, the summon
weights and the account pages stay usable.

What we took, after verifying it here:

| From him | Where it ended up |
| --- | --- |
| X11 as the Wine backend (`WAYLAND_DISPLAY=` cleared) | `scripts/launcher.sh`, `scripts/launch.py`, `FGOA_WINE_BACKEND` written by `install.sh` (default X11, `--use-wayland` for the other). His reason is not ours: he needs X11 for Zink on NVIDIA, while here Wine 11.17 refuses its Wayland driver outright (measured, see `INTERNALS.md`) and X11 is simply the path that was verified |
| `192.168.100.1/24` and `192.168.100.11/24` on `lo` for the platform probe | `install.sh`, `fgoa-cabinet-net.service`, plus the note in `launch.py` — see the cabinet role section below |
| Zeroing the `WGL_CONTEXT_FLAGS_ARB` robust-access request at `0x27AF7D` in `ago.exe` | `scripts/patch-ago-gl.py` — carried **unverified**: this machine is AMD + Mesa, where Mesa answers that request instead of refusing it, so the crash it cures does not happen here |

What we did not take, and why:

* **The touch shim (`touchshim.c`, mouse clicks re-sent as `WM_TOUCH`).** His build needs it because
  the game waits on "Please touch the screen" at the title. Here the same input works without it: the
  platform's own mouse-to-touch remap is switched on in the config `launch.py` writes
  (`"touch": {"remap": 1, ...}`, from the platform's `FGO_Runtime`/settings path), and clicking the
  title does reach the game — verified under X11 with the game advancing to `pre_start` on the card in
  `DEVICE/aime.txt`. A shim of our own would be a second, redundant layer.
* **Restarting everything when AMDaemon fails its probe.** His retry loop watches a screenshot of the
  window (ImageMagick + Pillow) and restarts ARTEMiS plus the game up to three times, which is how he
  gets past `ERROR 4102`. That error is his NVIDIA case: his log shows `amPlatformNvapiInit` failing
  because the prefix has no `nvapi64.dll`, and Linux's NVIDIA driver does not ship one. This project
  has never seen 4102, and a screenshot classifier in the launch path would be a lot of moving parts
  for a failure we cannot reproduce.
* **His English approach.** He turns the content hook off (`FGO_ZH_ENABLED=0`) and relies on the file
  overlay and the patched strings, having concluded that `fgozh.dll` cannot load into the game. It can:
  see the yana-arch section above — this project keeps the hook working and the overlay as a fallback.

## The cabinet role / ERROR 8404

Not from any kit; verified on this machine by walking the game's own test menu.

* A fresh install boots as **Satellite (Sub Unit)**: the startup screen reads
  `SYSTEM STARTUP (SATELLITE:SUB)` with `Location Server : WAIT (1679, 1)`, waits out the timeout and
  then dies with **ERROR 8404**. The scooby `GUIDE_EN.md` documents the same symptom as "8404 at
  boot" and gives the same cure.
* The state lives in `GameData/SDEJ/amdaemon_aux.json` as `lan_install.server`
  (`true` = main unit) and is rewritten on every boot from the game's own saved setting — which is why
  it looks like a saved preference and behaves like a heisenbug: whether a boot ends up as a main or a
  sub unit depends on the platform probe reaching a location server before the game gives up. The
  platform expects that server at **`192.168.100.1`** (`App/FGO_LocalNetwork.ps1`: `Server =
  192.168.100.1`, `Cabinet = 192.168.100.11`, `Subnet = 192.168.100.0`, and `launch.py` writes those
  same values into the config the game reads). On Windows the platform creates that network itself; in
  a Wine prefix nothing does, and the probe has no fallback — `fgohook.dll` only rewrites the *session*
  traffic to `127.0.0.1`, which is why a game that got past boot plays fine without it.
* **So the network is the thing to check first** (`ip -4 addr show lo`): `install.sh` now puts
  `192.168.100.1/24` and `192.168.100.11/24` there and keeps them across reboots
  (`fgoa-cabinet-net.service`), which is the same fix quinnjr's branch and yana-arch's Linux port both
  reached for — three independent routes to the same address. The idea to adopt it came from
  quinnjr's branch; the addresses themselves are the platform's own.
* Passing `-sm server` (what `FGO_Launcher.ps1` does when `cabinetMode` is `server`) does **not**
  change it; neither does editing or deleting the JSON — the file is regenerated with the same value.
* The cure is the game's own test menu, and it is a player action, not a script: on that screen
  press **F1** to enter the Game Test Menu, **F2** moves the arrow (down the list, wrapping) and
  **F1** confirms. Menu path: `Game Settings` → `Startup Mode` (it cycles between
  `Satellite (Sub Unit)` and `Satellite (Main Unit)`) → `Main Unit` → `Exit`. The process exits —
  start it again with Play. After that `lan_install.server` is `true` and the game starts normally.
  Any input arrangement works here, X11 or Wayland: it is the game reacting to a key, nothing more.
* **The menu route above is the cure, not the explanation.** It sets the role for the install and the
  game stays on it; but the *reason* a boot can come up as a sub unit is the probe, and that is what the
  cabinet network addresses address. Where the game stores the role between boots is still not known
  exactly, and this is not verified end to end yet: the addresses were added after the last clean test
  run, and on this machine they cannot be added without root (`sudo` asks for a password here), so
  `install.sh --verify` is what confirms them. If 8404 still appears with the addresses present, the
  next suspect is the timing of the probe against the title server's start — quinnjr's answer to that
  is a fresh ARTEMiS plus a relaunch, which is the piece of his work this project has deliberately not
  taken.

## Known open items

* **AimeDB (`:7777`)** accepts the game's connection and then fails to parse it
  (`Error parsing ADB header: Store ID cannot be 0!`, earlier also
  `Failed to decrypt 0a because Data must be aligned to block boundary in ECB mode`). Account
  creation, authentication and play are unaffected. Not investigated further.
* **A Faugus/Proton entry** does not exist: the scripts run the prefix directly with `wine`.
  (Noted for whoever wants it: `DOTNET_BUNDLE_EXTRACT_BASE_DIR=C:\dotnet_bundle_extract` and
  `WINEDLLOVERRIDES=xinput1_4=n,b` are what yana-arch's Lutris profile sets for Proton/UMU and
  gamepads.)
* **The English dataset is not complete by design**: a few event screens (co-op banners, co-op
  results, later event shops) remain Japanese artwork — that is the patch author's coverage, not a
  packaging bug.
