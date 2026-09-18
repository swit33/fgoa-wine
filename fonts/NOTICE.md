# Fonts in this folder — what they are and their licences

The launcher is a WPF application, and its `app.xaml` asks for two font families that no Linux
system provides: `Segoe UI, Yu Gothic UI, Microsoft YaHei UI` and `Cascadia Mono, Consolas`. When WPF
cannot resolve *any* of them it dies with FailFast before the window appears, so `install.sh` puts
these files into the Wine prefix and registers them in its registry.

**None of these files is a Microsoft font.** They are freely licensed fonts whose *internal family
name* (the `name` table, IDs 1 and 16) was rewritten to the requested family with
[`rename_font.py`](rename_font.py); the rest of the font is untouched.

| File | What it really is | Licence |
| --- | --- | --- |
| `SegoeUI.ttf`, `SegoeUI-Bold.ttf`, `SegoeUI-Italic.ttf`, `SegoeUI-BoldItalic.ttf` | Liberation Sans 2.1.5 | SIL Open Font License 1.1 — [LICENSE-liberation.txt](licenses/LICENSE-liberation.txt) |
| `Consolas.ttf`, `Consolas-Bold.ttf` | Liberation Mono 2.1.5 | SIL Open Font License 1.1 — [LICENSE-liberation.txt](licenses/LICENSE-liberation.txt) |
| `CascadiaMono.ttf` | DejaVu Sans Mono 2.37 | Bitstream Vera Fonts Licence + public domain — [LICENSE-dejavu.txt](licenses/LICENSE-dejavu.txt) |

You can confirm this yourself; the original names are still in the files:

```bash
fc-query fonts/SegoeUI.ttf | grep -E 'family|fullname'
#   family:   "Segoe UI"        <- the name we set, so WPF finds it
#   fullname: "Liberation Sans" <- the font it really is
strings -el fonts/SegoeUI.ttf | grep -i liberation      # the original name inside the file
```

Both licences allow redistribution, including in modified form, provided their notices travel with
the files — which is why the licence texts sit next to them. The family names themselves are set only
so that the launcher finds what it asks for; nothing here claims to *be* the Microsoft fonts, and no
Microsoft font file is included. The renaming is a functional requirement of the WPF application, not
a way around a licence.

If you would rather not ship font binaries at all, delete this folder's `*.ttf` files and run
`install.sh` after dropping any Liberation Sans/Mono or DejaVu Sans Mono TTF in here — then

```bash
python3 fonts/rename_font.py <source.ttf> fonts/SegoeUI.ttf "Segoe UI"
```

recreates them from the originals on your system (the installer only needs the files to be present).
