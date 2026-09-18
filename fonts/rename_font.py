#!/usr/bin/env python3
"""Renames the family inside a TTF (for Wine prefixes running WPF).

A WPF application dies with FailFast when it cannot find *any* family from its list (the
launcher wants "Segoe UI, Yu Gothic UI, Microsoft YaHei UI" and "Cascadia Mono, Consolas").
Neither Wine nor winetricks provides those names, so the font's name table is edited: the
family name (nameID 1 and 16) is replaced. The string is written at the same offset and only
ever shortened, so the other table entries do not shift.

  python3 rename_font.py --show  font.ttf
  python3 rename_font.py font.ttf out.ttf "Segoe UI"
"""
import struct
import sys


def name_records(data):
    """(offset, nameID, platform, language, length) for the name table records."""
    off = struct.unpack_from(">H", data, 4)[0]        # numTables
    name_off = None
    for i in range(off):
        base = 12 + i * 16
        tag = data[base:base + 4]
        if tag == b"name":
            name_off = struct.unpack_from(">I", data, base + 8)[0]
            break
    if name_off is None:
        raise SystemExit("no name table")
    count, storage = struct.unpack_from(">HH", data, name_off + 2)
    out = []
    for i in range(count):
        rec = name_off + 6 + i * 12
        plat, enc, lang, nid, length, offset = struct.unpack_from(">HHHHHH", data, rec)
        out.append((rec, plat, enc, lang, nid, length, name_off + storage + offset))
    return out


def read_name(data, entry):
    _rec, plat, _enc, _lang, _nid, length, soff = entry
    raw = data[soff:soff + length]
    return raw.decode("utf-16-be" if plat in (0, 3) else "latin-1", "replace")


def patch(path, out_path, new_family):
    data = bytearray(open(path, "rb").read())
    changed = []
    for entry in name_records(data):
        rec, plat, _enc, _lang, nid, length, soff = entry
        if nid not in (1, 16):                       # 1 = family, 16 = typographic family
            continue
        old = read_name(data, entry)
        if old == new_family:
            continue
        payload = new_family.encode("utf-16-be" if plat in (0, 3) else "latin-1")
        if len(payload) > length:
            print(f"  skipping nameID {nid}: '{new_family}' is longer than '{old}'")
            continue
        data[soff:soff + len(payload)] = payload
        data[soff + len(payload):soff + length] = b"\0" * (length - len(payload))
        struct.pack_into(">H", data, rec + 8, len(payload))   # length shrinks, offset stays
        changed.append((nid, old))
    if out_path == "-":
        return changed
    open(out_path, "wb").write(bytes(data))
    return changed


def main():
    if sys.argv[1] == "--show":
        for e in name_records(open(sys.argv[2], "rb").read()):
            if e[4] in (1, 2, 16, 17):
                print(f"  nameID {e[4]:>2} plat {e[1]}: {read_name(open(sys.argv[2],'rb').read(), e)!r}")
        return 0
    src, dst, family = sys.argv[1], sys.argv[2], sys.argv[3]
    changed = patch(src, dst, family)
    print(f"{src} -> {dst}: family = '{family}' ({len(changed)} records)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
