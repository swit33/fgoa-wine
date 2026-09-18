# Upstream, prior art, and where each fix came from

This glue was written against two upstream projects and one community kit. This file records what
came from where, so a future maintainer can retrace every change instead of guessing.

## The pieces

| Piece | Author | Notes |
| --- | --- | --- |
| FGO Arcade local platform (`本体`, `前端`) | **Cloud23333** | The server package, the Chinese front end and the file hook. V1.02 is the one to be on. |
| FGOAC scooby (English patch + launcher) | **githubuser420x** | `FGOAC scooby.exe`, `payload/`, `manifest.json`, `Apply-EN-Patch.ps1`, `GUIDE_EN.md`, and the compat layers in `compat/`. |
| `compat/fgoglcompat.dll` | arrived through the community | Aliases 18 NVIDIA-only OpenGL entry points onto ARB. Shipped as received, no licence file. |
| `compat/amd-shim/opengl32.dll` | **fluphus** ([fgo-arcade-amd-shim](https://github.com/fluphus/fgo-arcade-amd-shim), MIT) | Newer AMD/Intel layer: an `opengl32.dll` forwarder plus `amdcfg/amdOglpSettings.cfg`. Published as tested only on an RX 7900 XTX; reported to fail at the first battle on RX 500/6000/7600. This install uses the older `fgoglcompat.dll` instead (injected by `launch.py`). NVIDIA cards want PRIME render offload, not either layer. |
| `FGOAC-scooby-linux` | **yana-arch** (branch `linux-support`) | The prior Linux kit this project compared itself against. Three fixes were adopted from it — see below. |

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
`ip_unprivileged_port_start=0`, `ptrace_scope=0`, a `192.168.100.1/32` address on `lo` and a systemd
unit; it also needs no host `powershell` package. Their `setup-fgoa-linux.sh` never installs
`ps_shim.py` (the symlink it makes points `powershell.exe` at the *host* `pwsh`, which cannot run
`.exe` files) — here the installer wires the shim itself.

## The cabinet role / ERROR 8404

Not from any kit; verified on this machine by walking the game's own test menu.

* A fresh install boots as **Satellite (Sub Unit)**: the startup screen reads
  `SYSTEM STARTUP (SATELLITE:SUB)` with `Location Server : WAIT (1679, 1)`, waits out the timeout and
  then dies with **ERROR 8404**. The scooby `GUIDE_EN.md` documents the same symptom as "8404 at
  boot" and gives the same cure.
* The state lives in `GameData/SDEJ/amdaemon_aux.json` as `lan_install.server`
  (`true` = main unit) and is rewritten on every boot from the game's own saved setting.
* Passing `-sm server` (what `FGO_Launcher.ps1` does when `cabinetMode` is `server`) does **not**
  change it; neither does editing or deleting the JSON — the file is regenerated with the same value.
* The cure is the game's own menu, and it can be driven from Linux with the tools in this folder:
  focus the window (`hyprctl dispatch 'hl.dsp.focus({window="class:ago.exe"})'`), then
  `wine Server/python/python.exe tools/win-click.py key F1` — `F1` is confirm/enter, `F2` moves the
  arrow down the list with wraparound. Menu path: `Game Settings` → `Startup Mode` (cycles between
  `Satellite (Sub Unit)` and `Satellite (Main Unit)`) → `Main Unit` → `Exit` (reboot; the process
  exits, start it again with Play). After that `lan_install.server` is `true` and the game starts
  normally.

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
