# FGO Arcade on Linux — install guide

Runs **Fate/Grand Order Arcade** (Cloud23333's *local platform* build) with the
[**FGOAC scooby**](https://github.com/githubuser420x/FGOAC-scooby) English patch on Linux under
Wine, and gives it the launcher it expects.

This folder is **not a game download**. It holds only the glue that the shipped Windows front end
cannot provide on Linux: that launcher drives every action through PowerShell, which Wine cannot run,
so these scripts do the same work directly — generate the game's runtime config, start the local
server, apply the English dataset, and start the game with its hooks.

Everything technical (how the launcher's PowerShell calls are intercepted, why each binary patch
exists, where the fixes came from) lives in [`docs/`](docs/) — you do not need it to install.

---

## What you need

**A game folder that is already assembled** — the platform `本体` unpacked, `前端` **1.02** applied on
top of it, and the **FGOAC scooby** release unpacked over that. This installer does not unpack
anything: where the archives came from, in what format they were, and how they were merged is your
business, not its. What it does check is that the folder really is at that stage — if
`App/FGO_Runtime.dll`, `FGOAC scooby.exe`, `payload/` or `manifest.json` are missing it says so and
stops.

(Reference recipe, including the naming trap Google Drive creates, is in
[`docs/INTERNALS.md`](docs/INTERNALS.md#assembling-the-game-folder). 1.02 is cumulative, so 1.01 does
not have to be applied separately.)

**On the machine:**

* Linux x86_64, `wine` (11.x used here), `python3`, ~35 GB free disk, and one `sudo` for the
  privileged-port setting;
* **fontconfig** (`fc-match`) and a free font package providing **Liberation Sans/Mono** and
  **DejaVu Sans Mono** — the launcher's WPF front end asks for families no Linux system has, and
  `install.sh` renames these into the Wine prefix on the spot
  (`sudo pacman -S ttf-liberation ttf-dejavu` on Arch/CachyOS, `sudo apt install fonts-liberation
  fonts-dejavu-core` on Debian/Ubuntu; details in [`fonts/NOTICE.md`](fonts/NOTICE.md));
* a graphics driver that can do OpenGL 4.6 (Mesa works: a shim covers the NVIDIA-only extensions the
  game asks for).

## Install

```bash
cp -a fgoa-wine /path/to/game/          # this folder becomes <game>/fgoa-wine
/path/to/game/fgoa-wine/install.sh      # add --sysctl for the port-777 setting
```

`install.sh` uses the folder above itself as the game root; `--root <dir>` overrides that, and
`--verify` only checks an existing install without changing anything. Other flags: `--prefix <dir>`,
`--sysctl`, `--no-fonts`, `--no-shim`. Re-running it is safe — every step is idempotent.

The installer, in order:

1. checks that the game folder is the one described above and lists what is missing if not;
2. applies this project's layer — the `ago.exe` import fix, the English dataset (including the
   `fgozh.dll` fix that makes the release's own English hook work under Wine), and two server-side
   fixes;
3. creates the Wine prefix if needed and prepares it — the launcher's PowerShell shim, the WPF fonts
   **and their registry entries**, `~/.config/fgoa-wine/config.env`;
4. sets up the Mesa config the game's shaders need;
5. sets up the ports — warns (or with `--sysctl` fixes) the privileged 777, and moves the database off
   8888 if something else holds it;
6. verifies everything and prints what to do next.

**Result to look for:** the last line reads `RESULT: everything is in place.` — then follow the numbered hints it
prints.

## First run

```bash
./scripts/launcher.sh
```

The launcher's first start sets itself up (it checks the environment, applies the English patch and
creates an account called `Master`), then press **Play**. The first launch takes about a minute while
the game compiles shaders.

Before you press Play, one thing is worth doing on the launcher's pages:

* **Account** — the launcher's first run already created a starter account called `Master` and made it
  the current one, and the Account page handles any further accounts. (If the game is ever started with
  an empty `DEVICE/aime.txt` on its own, it creates the broken `aime_id 4294967295`; `install.sh
  --fix-account` cleans that up, and `launch.py` refuses to start with an empty card while a valid
  account exists.)
* **Cards and Deck** — build a deck (double-click up to 30 cards). The game plays the deck that was
  in hand at Play; as shipped it contains one card, so only Mash appears.

**If the game shows `SYSTEM STARTUP (SATELLITE:SUB)` with `Location Server : WAIT`, followed by
ERROR 8404** — the game thinks it is a sub cabinet. Fix it on that screen: press **F1** (Game Test
Menu; **F2** moves the arrow, **F1** confirms) → **Game Settings** → **Startup Mode** →
**Main Unit** → **Exit**, then Play again. One-time per install.

## Day to day

```bash
./scripts/launcher.sh         # the shipping launcher — the normal way to play
./scripts/play.sh             # start the game directly, no launcher
./scripts/server.sh           # start the local server on its own
./scripts/server.sh stop      # stop it (do not kill MariaDB by hand, see below)
./install.sh --verify         # is everything still in place?
./uninstall.sh                # remove our layer from the prefix (game and saves stay)
```

Screen mode, resolution, input and frame rate come from `App/fgo-launcher.json` (the launcher's
Settings page writes it); the cabinet role sits in the same file as `cabinetMode`.

**Summon rates** live in `Server/artemis/config/fgo_summon_weights.json` and are edited from the
launcher: **Cards and Deck → Draw Rates**. Every card has a `Weight (integer)` column and a live
`Draw Chance` beside it; `Even for All` / `Only Selected (100%)` / `Exclude Selected` work on the
selected rows, and `Save - Applies to the Next Draw` writes the file. The server reads weights at
draw time, so no restart is needed. As shipped every weight is 0 except one card, so every summon
returns the same Servant — that is a config value, not a bug.

## If something goes wrong

| Symptom | What to do |
| --- | --- |
| `ERROR 8404` at boot, `Location Server : WAIT` | Cabinet role — see "First run" above. |
| `ERROR 4102` | The local server is not reachable. Start it from the launcher and wait for it to report ready, or run `./scripts/server.sh`. |
| Launcher window ignores the mouse | Wine-side quirk: close the launcher and start it again. Clicks made while a modal dialog is open are swallowed by design. |
| `PermissionError` / `Errno 13` on port 777 | Re-run `install.sh --sysctl` (or set `net.ipv4.ip_unprivileged_port_start = 777` yourself). |
| MariaDB will not start next time, "serious error" dialog | The database was killed instead of shut down. Always stop it with `./scripts/server.sh stop`. |
| `Cannot use Aime card` at the title | The first message to the local server timed out on that boot: close the game, check the server is ready, press Play again. |
| Game window opens and closes (exit code 22) | Try windowed 1280x720 on the primary monitor, and keep `logs/ago-crash-*.dmp` if you report it. |
| Nothing happens on Play | Check `logs/fgo-launch-<date>.log` (the game's live output) and `/tmp/fgoa-shim.log` (every launcher call). |

## Manual install (what the installer automates)

With the game folder ready, the installer's own layer is these three commands:

```bash
./scripts/patch-ago-import.py <root>/App/ago.exe SetWindowFeedbackSetting IsWindow --apply
./scripts/apply-en.py <root> --apply
./scripts/patch-server.py <root> --apply
```

## What is in here

| Path | What it is |
| --- | --- |
| `install.sh`, `uninstall.sh` | The installer and its reverse. |
| `scripts/launcher.sh`, `scripts/play.sh` | Start the launcher / start the game directly. |
| `scripts/server.sh` | Start and stop the local server (MariaDB + ARTEMiS). |
| `scripts/launch.py` | What actually starts the game: runtime config, hooks, deck channel, cabinet role. |
| `scripts/apply-en.py`, `scripts/patch-ago-import.py`, `scripts/patch-server.py` | The three text/binary patches, each idempotent with its own `--verify`. |
| `scripts/{set-ports,fix-account,stop-watcher}.py` | Port fixing, broken-account repair, and the server's idle watcher. |
| `shim/` | The launcher's PowerShell replacement (PE stub + bash dispatcher + handlers). |
| `config/drirc.d/99-fgoa.conf` | The Mesa setting the game's shaders need. |
| `fonts/` | The font mapping the installer applies from your system (`fonts/NOTICE.md`). |
| `docs/` | How it works inside, and where each fix came from. |

Environment: `FGOA_ROOT` (game root), `WINEPREFIX` (default `~/.local/share/fgoa-wine/prefix`); both
are written into `~/.config/fgoa-wine/config.env` by the installer.

## Credits

This project is glue around other people's work, and it says so everywhere:

* **[githubuser420x](https://github.com/githubuser420x) — [FGOAC-scooby](https://github.com/githubuser420x/FGOAC-scooby)**:
the English patch and the launcher this folder exists to run. Its `payload/`, `manifest.json`,
`Apply-EN-Patch.ps1` and `compat/` are used exactly as shipped — nothing here reimplements them.
* **[yana-arch](https://github.com/yana-arch) — [FGOAC-scooby-linux](https://github.com/yana-arch/FGOAC-scooby-linux)**
(branch `linux-support`): two of the fixes here are theirs — the five-byte `fgozh.dll` patch that lets
the release's own English hook load under Wine, and the two `Server/tools/` fixes. What was taken,
and what was measured before taking it, is in [`docs/UPSTREAM.md`](docs/UPSTREAM.md).
* **Cloud23333** — the FGO Arcade local platform (`本体`, `前端`) that everything runs on.
* The fonts the launcher needs are **Liberation Sans/Mono** (SIL OFL 1.1) and **DejaVu Sans Mono**
  (Bitstream Vera licence), taken from your system and renamed locally by the installer — none of them
  ships with this project, and no Microsoft font is involved. See
  [`fonts/NOTICE.md`](fonts/NOTICE.md).
* **[fluphus](https://github.com/fluphus) — [fgo-arcade-amd-shim](https://github.com/fluphus/fgo-arcade-amd-shim)**
(MIT): the AMD/Intel OpenGL layer that ships inside the platform's `compat/` folder.

Fate/Grand Order Arcade is SEGA's and TYPE-MOON's. Nothing here contains game data or is sold; it is
glue for a fan translation applied to files you already have.
