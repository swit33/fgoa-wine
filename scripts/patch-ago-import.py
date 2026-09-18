#!/usr/bin/env python3
"""Замена имени функции в таблице импортов PE (x64).

Wine аборится на нереализованной заглушке USER32.SetWindowFeedbackSetting, которую
ago.exe импортирует статически. Имя в таблице имён импорта меняется на существующий
безвредный экспорт user32 (IsWindow: принимает HWND, ничего не делает, возвращает BOOL);
хвост строки добивается нулями, длина сохраняется.

  python3 patch_import.py ago.exe                                  # показать
  python3 patch_import.py ago.exe SetWindowFeedbackSetting IsWindow --apply
"""
import struct
import sys


def rva_to_off(sections, rva):
    for va, vsize, raw, rawsize in sections:
        if va <= rva < va + max(vsize, rawsize):
            return raw + (rva - va)
    raise ValueError(f"rva {rva:#x} вне секций")


def cstr(data, off):
    return data[off:data.index(b"\0", off)].decode("ascii", "replace")


def sections_of(data):
    pe = struct.unpack_from("<I", data, 0x3C)[0]
    assert data[pe:pe + 4] == b"PE\0\0", "не PE"
    nsec = struct.unpack_from("<H", data, pe + 6)[0]
    optsize = struct.unpack_from("<H", data, pe + 20)[0]
    opt = pe + 24
    assert struct.unpack_from("<H", data, opt)[0] == 0x20B, "не PE32+ (x64)"
    out = []
    for i in range(nsec):
        off = pe + 24 + optsize + i * 40
        vsize, va, rawsize, raw = struct.unpack_from("<IIII", data, off + 8)
        out.append((va, vsize, raw, rawsize))
    return opt, out


def import_names(data, sections, ddir_index, entry_size, max_entries=64):
    """Имена функций из обычного (ddir 1, по 20 байт) или delay (ddir 13, по 32) импорта."""
    opt, _ = sections_of(data)
    rva, size = struct.unpack_from("<II", data, opt + 112 + ddir_index * 8)
    if not rva:
        return []
    desc = rva_to_off(sections, rva)
    found = []
    for _ in range(max_entries):
        raw = data[desc:desc + 32]
        if entry_size == 20:
            oft, _stamp, _fwd, name_rva, first = struct.unpack_from("<IIIII", raw)
            if not any((oft, name_rva, first)):
                break
            names_rva = oft or first
        else:
            attrs, name_rva, _h, _iat, names_rva = struct.unpack_from("<IIIII", raw)
            if attrs == 0:
                break
        dll = cstr(data, rva_to_off(sections, name_rva))
        t = rva_to_off(sections, names_rva)
        while True:
            value = struct.unpack_from("<Q", data, t)[0]
            if value == 0:
                break
            if not value >> 63:
                found.append(((("delay:" if entry_size == 32 else "") + dll),
                              rva_to_off(sections, value & 0x7FFFFFFF) + 2))
            t += 8
        desc += entry_size
    return found


def main():
    path, want, repl = sys.argv[1], sys.argv[2], sys.argv[3]
    apply_ = "--apply" in sys.argv

    data = open(path, "rb").read()
    _opt, sections = sections_of(data)
    hits = []
    for entry, off in (import_names(data, sections, 1, 20) +
                       import_names(data, sections, 13, 32)):
        if cstr(data, off) == want:
            hits.append((entry, off))
    for entry, off in hits:
        print(f"{entry}: '{want}' @ {off} (0x{off:x})")
    if not hits:
        print("в таблицах импорта не найдено")
        return 1
    if not apply_:
        print("сухой прогон; добавь --apply")
        return 0

    before = open(path, "rb").read()
    payload = repl.encode() + b"\0" * (len(want) - len(repl))
    assert len(payload) == len(want)
    for _entry, off in hits:
        data = data[:off] + payload + data[off + len(want):]
    open(path + ".orig", "wb").write(before)
    open(path, "wb").write(data)
    print(f"заменено: {len(hits)}; бэкап рядом: {path}.orig")
    return 0


if __name__ == "__main__":
    sys.exit(main())
