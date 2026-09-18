# Fonts — not shipped, prepared locally by the installer

The launcher is a WPF application whose `app.xaml` asks for two font families that no Linux system
provides: `Segoe UI, Yu Gothic UI, Microsoft YaHei UI` and `Cascadia Mono, Consolas`. When WPF cannot
resolve *any* family from that list it dies with FailFast before a window appears at all.

**This project ships no font files.** Instead `install.sh` takes a freely licensed font from your
system, rewrites its internal family name (the `name` table, IDs 1 and 16) with
[`rename_font.py`](rename_font.py), writes the result into the Wine prefix and registers it there.
That way the binary that ends up in your prefix is built on your machine from a font you already
have — and its licence stays where it belongs, with your distribution's font package.

## What it looks for

| Family the launcher asks for | Taken from | Licence of that source font |
| --- | --- | --- |
| `Segoe UI` (regular, bold, italic, bold italic) | **Liberation Sans** | SIL Open Font License 1.1 |
| `Consolas` (regular, bold) | **Liberation Mono** | SIL Open Font License 1.1 |
| `Cascadia Mono` | **DejaVu Sans Mono** | Bitstream Vera Fonts Licence + public domain |

Install them with your package manager:

```bash
sudo pacman -S ttf-liberation ttf-dejavu           # Arch / CachyOS
sudo apt install fonts-liberation fonts-dejavu-core # Debian / Ubuntu
```

`fonts.list` holds the mapping (registry name | file to write into the prefix | fontconfig pattern |
family to set) and can be edited if you prefer different source fonts. `install.sh --verify` reports
missing pieces, and `install.sh --no-fonts` skips this step entirely if you prepare the prefix
yourself.

## Why the names are what they are

The names `Segoe UI`, `Consolas` and `Cascadia Mono` are Microsoft's *trademarks*, and they are set
here only because the launcher asks for them by name — it is a functional requirement, not a claim of
authorship. No Microsoft font file is used, copied or redistributed by this project, and the files
produced on your machine remain subject to the licence of the font they came from (the two in the
table are free for redistribution, including modified copies, under the terms linked above; both
require their licence text to accompany the font, which is why the originals stay where your package
manager put them).

To check what any file in a prefix really is:

```bash
fc-query "$WINEPREFIX/drive_c/windows/Fonts/SegoeUI.ttf" | grep -E 'family|fullname'
#   family:   "Segoe UI"        <- the name we set, so WPF finds it
#   fullname: "Liberation Sans" <- the font it really is
```
