#!/usr/bin/env python3
"""Накладывает английский набор FGOAC scooby прямо на файлы игры.

Хук App\\zh\\fgozh.dll под Wine падает в DllMain: ntdll не экспортирует
NtQueryInformationByName, fgozh.dll считает это фатальным и возвращает FALSE — inject.exe
после этого убивает игру. Фаза 0 снимает это пятью байтами (идея и смещение:
yana-arch/FGOAC-scooby-linux, ветка linux-support), и дальше хук грузится сам.
Пока хук не загружен (или если его снова сломает новая сборка), работает обход —
делаем то же самое заранее:
  1) ресурсы: App/zh/<путь> -> App/<путь>, список берём из App/zh/text-outputs.json;
  2) строки внутри ago.exe: правка по смещениям из App/zh/executable-text.json (utf-8,
     английский всегда короче японского, поэтому влезает на место, хвост добивается нулями).

Бэкапы не перезаписываются, так что повторный запуск сохраняет именно оригинал:
  заменённые файлы -> _en-overlay-backup/<путь>, ago.exe -> App/ago.exe.en-overlay.bak

  python3 fgoa_apply_en.py <install_root>            # показать план (ничего не меняет)
  python3 fgoa_apply_en.py <install_root> --apply    # накатить
  python3 fgoa_apply_en.py <install_root> --verify   # сверить, что уже наложено
"""
import hashlib
import json
import os
import shutil
import sys
import time

BACKUP_DIR = "_en-overlay-backup"

# Эти два файла правит patch-server.py (правки из yana-arch). Их сверяет его собственный
# --verify, а копия payload не должна их перезаписывать: иначе повторный накат английского
# (кнопка Apply EN patch в лончере) возвращал бы их к исходному виду.
SERVER_PATCHED = {"Server/tools/fgo_account.py", "Server/tools/fgo_account_actions.py"}

# 5 байт в App\\zh\\fgozh.dll: mov eax,0Ch (MH_ERROR_FUNCTION_NOT_FOUND) -> xor eax,eax
FGOZH_REL = "App/zh/fgozh.dll"
FGOZH_OFFSET = 0x19E99
FGOZH_ABORT = bytes.fromhex("b80c000000")
FGOZH_PATCHED = bytes.fromhex("31c0909090")


def sha256(path):
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def fgozh_ok(data, expected):
    """Манифест описывает нетронутый fgozh.dll; после патча хука файл сверяем,
    откатив пять байт на место — иначе проверка payload всегда будет ругаться."""
    if sha256_bytes(data) == expected:
        return True
    if data[FGOZH_OFFSET:FGOZH_OFFSET + 5] == FGOZH_PATCHED:
        rolled = bytearray(data)
        rolled[FGOZH_OFFSET:FGOZH_OFFSET + 5] = FGOZH_ABORT
        return sha256_bytes(bytes(rolled)) == expected
    return False


def patch_fgozh(root, mode):
    """Фаза 0: разрешить fgozh.dll грузиться под Wine (см. модульный докстринг).
    -> (состояние, проблемы)
    """
    path = os.path.join(root, FGOZH_REL)
    if not os.path.isfile(path):
        return "нет файла", []
    data = open(path, "rb").read()
    head = data[FGOZH_OFFSET:FGOZH_OFFSET + 5]
    if head == FGOZH_PATCHED:
        return "хук грузится (пропатчен)", []
    if head != FGOZH_ABORT:
        return ("неизвестная сборка",
                [f"fgozh.dll: на {hex(FGOZH_OFFSET)} не то, что ожидалось ({head.hex()}) — "
                 "патч хука не наложен, перевод работает обходным путём"])
    if mode == "verify":
        return "не пропатчен", ["fgozh.dll: патч хука не наложен — английский идёт обходом"]
    if mode != "apply":
        return "будет пропатчен", []
    backup_path = path + ".wine-hook.bak"
    if not os.path.exists(backup_path):
        shutil.copy2(path, backup_path)
    patched = bytearray(data)
    patched[FGOZH_OFFSET:FGOZH_OFFSET + 5] = FGOZH_PATCHED
    with open(path, "wb") as fh:
        fh.write(patched)
    return "пропатчен (хук теперь грузится)", []


def read_json(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def backup(root, rel, dry_run):
    """Сохраняет оригинал файла один раз."""
    src = os.path.join(root, rel)
    dst = os.path.join(root, BACKUP_DIR, rel)
    if not os.path.isfile(src) or os.path.exists(dst):
        return False
    if not dry_run:
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)
    return True


def overlay_files(root, rels, mode):
    """mode: plan | apply | verify -> (копий, бэкапов, проблем)."""
    copied = backups = 0
    problems = []
    for rel in rels:
        src = os.path.join(root, "App", "zh", rel.replace("\\", "/"))
        rel_norm = rel.replace("\\", "/")
        dst = os.path.join(root, "App", rel_norm)
        if not os.path.isfile(src):
            problems.append(f"нет источника: App/zh/{rel_norm}")
            continue
        if mode == "verify":
            if not os.path.isfile(dst) or hashlib.sha256(open(dst, "rb").read()).digest() != \
                    hashlib.sha256(open(src, "rb").read()).digest():
                problems.append(f"не наложено: App/{rel_norm}")
            else:
                copied += 1
            continue
        if backup(root, "App/" + rel_norm, mode == "plan"):
            backups += 1
        if mode == "plan":
            copied += 1
            continue
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copyfile(src, dst)
        copied += 1
    return copied, backups, problems


def overlay_exe_strings(root, mode):
    """Правка строк внутри ago.exe. -> (правок, пропусков, пустых, проблем)."""
    exe = os.path.join(root, "App", "ago.exe")
    table = read_json(os.path.join(root, "App", "zh", "executable-text.json"))
    data = bytearray(open(exe, "rb").read())
    entries = []
    for e in table:
        name, _, off = e["id"].partition("||")
        if name == "ago.exe":
            entries.append((int(off), e["原文"], e["译文"]))
    entries.sort()
    patched = skipped = empty = 0
    problems = []
    prev_end = -1
    for off, jp, en in entries:
        raw_jp, raw_en = jp.encode("utf-8"), en.encode("utf-8")
        if not raw_en or raw_en == raw_jp:
            # Пустой или совпадающий перевод — хук такие записи не трогает
            # (среди них исходники GLSL-шейдеров и одиночные каны).
            empty += 1
            continue
        if off < prev_end:
            problems.append(f"перекрытие смещений на {off}")
            skipped += 1
            continue
        if mode == "verify":
            # после наката на месте английский текст, а не японский оригинал
            if data[off:off + len(raw_en)] == raw_en and data[off + len(raw_en)] == 0:
                patched += 1
            else:
                problems.append(f"не пропатчено: {off}")
            prev_end = off + len(raw_jp)
            continue
        if data[off:off + len(raw_en)] == raw_en and data[off + len(raw_en)] == 0:
            patched += 1          # уже наложено — повторный запуск безопасен
            prev_end = off + len(raw_jp)
            continue
        if data[off:off + len(raw_jp)] != raw_jp:
            problems.append(f"по смещению {off} не то, что ожидалось")
            skipped += 1
            continue
        if data[off + len(raw_jp)] != 0:
            problems.append(f"строка на {off} не терминирована нулём")
            skipped += 1
            continue
        if len(raw_en) > len(raw_jp):
            problems.append(f"английский длиннее на {off} ({len(raw_en)}>{len(raw_jp)})")
            skipped += 1
            continue
        prev_end = off + len(raw_jp)
        if mode == "apply":
            data[off:off + len(raw_jp)] = raw_en + b"\0" * (len(raw_jp) - len(raw_en))
        patched += 1
    if mode == "apply" and patched:
        bak = exe + ".en-overlay.bak"
        if not os.path.exists(bak):
            shutil.copy2(exe, bak)
        with open(exe, "wb") as fh:
            fh.write(data)
    return patched, skipped, empty, problems


def manifest_ok(rel, dst, expected):
    if rel == FGOZH_REL:
        return fgozh_ok(open(dst, "rb").read(), expected)
    return sha256(dst) == expected


def overlay_list(root):
    """Список файлов, которые подменяет хук.

    Это text-outputs.json (текстовые/данные) плюс 240 перерисованных спрайтов
    rom/sprite/*.farc — вместе ровно 1683, то есть тот самый REDIRECT_INDEX,
    который хук печатает в logs/fgozh.log. Шрифт rom/font/* хук не подменяет
    (в наборе лежит CJK-шрифт его китайской сборки) — оставляем родной.
    """
    rels = {r.replace("\\", "/") for r in read_json(os.path.join(root, "App", "zh", "text-outputs.json"))}
    meta = {"fgozh.dll", "executable-text.json", "text-outputs.json", "en-patch.json"}
    zh = os.path.join(root, "App", "zh")
    for dirpath, _dirs, files in os.walk(zh):
        for name in files:
            rel = os.path.relpath(os.path.join(dirpath, name), zh).replace("\\", "/")
            if rel in meta or rel.startswith("rom/font/"):
                continue
            if name.endswith((".bak", ".orig", ".wine-hook.bak")):
                continue          # наши же бэкапы в App/zh не разносим по игре
            rels.add(rel)
    return sorted(rels)


def overlay_payload(root, mode):
    """Фаза 1, как в оригинальном Apply-EN-Patch.ps1: скопировать payload/** в установку
    и сверить каждый файл по manifest.json.

    Именно этот шаг кладёт английские файлы в App/zh/ (и EN-скрипты, и Server/tools).
    Вторая фаза (overlay_files) потом разносит App/zh/** по родным путям игры — то, что
    хук fgozh.dll делал бы в памяти.
    """
    payload = os.path.join(root, "payload")
    if not os.path.isdir(payload):
        return 0, 0, 0, ["нет папки payload — английский набор не приложен"]
    manifest = read_json(os.path.join(root, "manifest.json"))
    files = manifest["files"]
    copied, separate, problems = 0, 0, []
    for rel, expected in sorted(files.items()):
        rel = rel.replace("\\", "/")
        src, dst = os.path.join(payload, rel), os.path.join(root, rel)
        if rel in SERVER_PATCHED and mode == "verify":
            # их правит patch-server.py, и он же их проверяет: после его правки файл
            # намеренно расходится с манифестом
            separate += 1
            continue
        from_payload = os.path.isfile(src)
        if rel in SERVER_PATCHED:
            # их правит patch-server.py, и он же их проверяет: не затираем уже наложенное
            # (иначе кнопка Apply EN patch в лончере откатывала бы серверные правки)
            copied += 1
            continue
        if not from_payload:
            # часть манифеста (сам FGOAC scooby.exe) лежит прямо в корне — только сверяем
            if mode == "verify" or os.path.isfile(dst):
                if os.path.isfile(dst) and manifest_ok(rel, dst, expected):
                    copied += 1
                else:
                    problems.append(f"не совпадает с манифестом: {rel}")
            continue
        if mode == "verify":
            if os.path.isfile(dst) and manifest_ok(rel, dst, expected):
                copied += 1
            else:
                problems.append(f"не совпадает с манифестом: {rel}")
            continue
        if sha256(src) != expected:
            problems.append(f"хэш payload не сходится: {rel}")
            continue
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copyfile(src, dst)
        copied += 1
    return copied, len(files), separate, problems


def main():
    root = os.path.abspath(sys.argv[1])
    mode = "verify" if "--verify" in sys.argv else ("apply" if "--apply" in sys.argv else "plan")
    payload_copied, manifest_total, payload_separate, payload_problems = overlay_payload(root, mode)
    # патч хука строго после копии payload: она возвращает файл к нетронутому виду
    fgozh_state, fgozh_problems = patch_fgozh(root, mode)
    # список оверлея строим ПОСЛЕ payload: только он кладёт в App/zh спрайты и прочее
    rels = overlay_list(root)
    copied, backups, problems = overlay_files(root, rels, mode)
    patched, skipped, empty, exe_problems = overlay_exe_strings(root, mode)

    if mode == "apply":
        cfg_path = os.path.join(root, "App", "fgo-launcher.json")
        try:
            with open(cfg_path, encoding="utf-8") as fh:
                cfg = json.load(fh)
            if cfg.get("chineseEnabled") is not True:
                cfg["chineseEnabled"] = True
                with open(cfg_path, "w", encoding="utf-8") as fh:
                    json.dump(cfg, fh, ensure_ascii=False, indent=2)
                    fh.write("\n")
                print("  chineseEnabled=true в App/fgo-launcher.json (игра читает App\\zh)")
        except (OSError, ValueError) as exc:
            print(f"  не удалось выставить chineseEnabled: {exc}")
        manifest = read_json(os.path.join(root, "manifest.json"))
        marker = {"version": manifest.get("version"),
                  "appliedUtc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                  "manifestHash": manifest.get("manifestHash")}
        marker_path = os.path.join(root, "App", "zh", "en-patch.json")
        os.makedirs(os.path.dirname(marker_path), exist_ok=True)
        with open(marker_path, "w", encoding="utf-8") as fh:
            json.dump(marker, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
        print(f"  маркер: App/zh/en-patch.json (версия {marker['version']})")

    print(f"режим: {mode}")
    print(f"  payload по манифесту: {payload_copied}/{manifest_total - payload_separate} файлов"
          + (f"  (+{payload_separate} правит patch-server.py)" if payload_separate else ""))
    print(f"  хук zh (fgozh.dll):  {fgozh_state}")
    print(f"  ресурсов обработано: {copied}/{len(rels)}  (бэкапов создано: {backups})")
    print(f"  строк в ago.exe:     {patched}  (пропущено: {skipped}, пустой перевод: {empty})")
    all_problems = payload_problems + fgozh_problems + problems + exe_problems
    if all_problems:
        print(f"  проблемы ({len(all_problems)}):")
        for line in all_problems[:15]:
            print("    " + line)
    if mode == "plan":
        print("  ничего не изменено; для наката добавь --apply")
    return 1 if all_problems else 0


if __name__ == "__main__":
    sys.exit(main())
