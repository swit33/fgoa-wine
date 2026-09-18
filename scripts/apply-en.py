#!/usr/bin/env python3
"""Applies the FGOAC scooby English dataset straight onto the game's files.

The App\\zh\\fgozh.dll hook dies in DllMain under Wine: ntdll does not export
NtQueryInformationByName, fgozh.dll treats that as fatal and returns FALSE, after which
inject.exe kills the launch. Phase 0 removes that with five bytes (idea and offset:
yana-arch/FGOAC-scooby-linux, branch linux-support), and the hook then loads by itself.
While the hook does not load (or when a future build breaks it again) the workaround runs:
we do the same thing ahead of time:
  1) resources: App/zh/<path> -> App/<path>, the list comes from App/zh/text-outputs.json;
  2) strings inside ago.exe: patched at the offsets from App/zh/executable-text.json
     (English is always shorter than Japanese, so it fits and the tail is zero-padded).

Backups are never overwritten, so a re-run still keeps the true original:
  replaced files -> _en-overlay-backup/<path>, ago.exe -> App/ago.exe.en-overlay.bak

  python3 apply-en.py <install_root>                 # show the plan (changes nothing)
  python3 apply-en.py <install_root> --apply         # apply
  python3 apply-en.py <install_root> --verify        # check what is already applied
"""
import hashlib
import json
import os
import shutil
import sys
import time

BACKUP_DIR = "_en-overlay-backup"

# These two files are patched by patch-server.py (fixes from yana-arch). Its own --verify
# checks them, and the payload copy must not overwrite them: otherwise applying English
# again (the launcher's Apply EN patch button) would restore them to the pristine state.
SERVER_PATCHED = {"Server/tools/fgo_account.py", "Server/tools/fgo_account_actions.py"}

# 5 bytes in App\\zh\\fgozh.dll: mov eax,0Ch (MH_ERROR_FUNCTION_NOT_FOUND) -> xor eax,eax
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
    """The manifest describes a pristine fgozh.dll; once the hook is patched the file is
    checked with those five bytes rolled back, or the payload check would always complain."""
    if sha256_bytes(data) == expected:
        return True
    if data[FGOZH_OFFSET:FGOZH_OFFSET + 5] == FGOZH_PATCHED:
        rolled = bytearray(data)
        rolled[FGOZH_OFFSET:FGOZH_OFFSET + 5] = FGOZH_ABORT
        return sha256_bytes(bytes(rolled)) == expected
    return False


def patch_fgozh(root, mode):
    """Phase 0: let fgozh.dll load under Wine (see the module docstring).
    -> (state, problems)
    """
    path = os.path.join(root, FGOZH_REL)
    if not os.path.isfile(path):
        return "no such file", []
    data = open(path, "rb").read()
    head = data[FGOZH_OFFSET:FGOZH_OFFSET + 5]
    if head == FGOZH_PATCHED:
        return "hook loads (patched)", []
    if head != FGOZH_ABORT:
        return ("unknown build",
                [f"fgozh.dll: {hex(FGOZH_OFFSET)} holds {head.hex()} instead of the expected "
                 "bytes - the hook is not patched, English runs through the workaround"])
    if mode == "verify":
        return "not patched", ["fgozh.dll: the hook is not patched - English runs via the workaround"]
    if mode != "apply":
        return "will be patched", []
    backup_path = path + ".wine-hook.bak"
    if not os.path.exists(backup_path):
        shutil.copy2(path, backup_path)
    patched = bytearray(data)
    patched[FGOZH_OFFSET:FGOZH_OFFSET + 5] = FGOZH_PATCHED
    with open(path, "wb") as fh:
        fh.write(patched)
    return "patched (the hook now loads)", []


def read_json(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def backup(root, rel, dry_run):
    """Keeps the original file once."""
    src = os.path.join(root, rel)
    dst = os.path.join(root, BACKUP_DIR, rel)
    if not os.path.isfile(src) or os.path.exists(dst):
        return False
    if not dry_run:
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)
    return True


def overlay_files(root, rels, mode):
    """mode: plan | apply | verify -> (copied, backups, problems)."""
    copied = backups = 0
    problems = []
    for rel in rels:
        src = os.path.join(root, "App", "zh", rel.replace("\\", "/"))
        rel_norm = rel.replace("\\", "/")
        dst = os.path.join(root, "App", rel_norm)
        if not os.path.isfile(src):
            problems.append(f"missing source: App/zh/{rel_norm}")
            continue
        if mode == "verify":
            if not os.path.isfile(dst) or hashlib.sha256(open(dst, "rb").read()).digest() != \
                    hashlib.sha256(open(src, "rb").read()).digest():
                problems.append(f"not overlaid: App/{rel_norm}")
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
    """Patches the strings inside ago.exe. -> (patched, skipped, empty, problems)."""
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
            # An empty or identical translation is left alone by the hook too
            # (those entries include GLSL shader sources and lone kana).
            empty += 1
            continue
        if off < prev_end:
            problems.append(f"overlapping offsets at {off}")
            skipped += 1
            continue
        if mode == "verify":
            # after patching the English text sits there, not the Japanese original
            if data[off:off + len(raw_en)] == raw_en and data[off + len(raw_en)] == 0:
                patched += 1
            else:
                problems.append(f"not patched: {off}")
            prev_end = off + len(raw_jp)
            continue
        if data[off:off + len(raw_en)] == raw_en and data[off + len(raw_en)] == 0:
            patched += 1          # already applied - a re-run is safe
            prev_end = off + len(raw_jp)
            continue
        if data[off:off + len(raw_jp)] != raw_jp:
            problems.append(f"offset {off} does not hold what was expected")
            skipped += 1
            continue
        if data[off + len(raw_jp)] != 0:
            problems.append(f"the string at {off} is not NUL-terminated")
            skipped += 1
            continue
        if len(raw_en) > len(raw_jp):
            problems.append(f"English is longer at {off} ({len(raw_en)}>{len(raw_jp)})")
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
    """The list of files the hook overrides.

    That is text-outputs.json (text/data) plus the 240 redrawn sprite archives in
    rom/sprite/*.farc - exactly 1683 together, the very REDIRECT_INDEX the hook
    prints into logs/fgozh.log. rom/font/* is not overridden by the hook either
    (the dataset carries the CJK font of his Chinese build) - the original stays.
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
                continue          # our own backups in App/zh are not spread over the game
            rels.add(rel)
    return sorted(rels)


def overlay_payload(root, mode):
    """Phase 1, as in the original Apply-EN-Patch.ps1: copy payload/** into the install
    and verify every file against manifest.json.

    This is the step that puts the English files into App/zh/ (and Server/tools).
    Phase 2 (overlay_files) then spreads App/zh/** over the game's own paths - what the
    fgozh.dll hook would have done in memory.
    """
    payload = os.path.join(root, "payload")
    if not os.path.isdir(payload):
        return 0, 0, 0, ["no payload folder - the English dataset was not shipped"]
    manifest = read_json(os.path.join(root, "manifest.json"))
    files = manifest["files"]
    copied, separate, problems = 0, 0, []
    for rel, expected in sorted(files.items()):
        rel = rel.replace("\\", "/")
        src, dst = os.path.join(payload, rel), os.path.join(root, rel)
        if rel in SERVER_PATCHED and mode == "verify":
            # patch-server.py patches them and verifies them: once patched the file
            # deliberately differs from the manifest
            separate += 1
            continue
        from_payload = os.path.isfile(src)
        if rel in SERVER_PATCHED:
            # patch-server.py patches and verifies them: do not clobber what is applied
            # (otherwise the launcher's Apply EN patch button would roll them back)
            copied += 1
            continue
        if not from_payload:
            # part of the manifest (FGOAC scooby.exe itself) sits in the root - verify only
            if mode == "verify" or os.path.isfile(dst):
                if os.path.isfile(dst) and manifest_ok(rel, dst, expected):
                    copied += 1
                else:
                    problems.append(f"does not match the manifest: {rel}")
            continue
        if mode == "verify":
            if os.path.isfile(dst) and manifest_ok(rel, dst, expected):
                copied += 1
            else:
                problems.append(f"does not match the manifest: {rel}")
            continue
        if sha256(src) != expected:
            problems.append(f"payload hash mismatch: {rel}")
            continue
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copyfile(src, dst)
        copied += 1
    return copied, len(files), separate, problems


def main():
    root = os.path.abspath(sys.argv[1])
    mode = "verify" if "--verify" in sys.argv else ("apply" if "--apply" in sys.argv else "plan")
    payload_copied, manifest_total, payload_separate, payload_problems = overlay_payload(root, mode)
    # the hook patch strictly after the payload copy: that restores the pristine file
    fgozh_state, fgozh_problems = patch_fgozh(root, mode)
    # the overlay list is built AFTER the payload: only it puts sprites into App/zh
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
                print("  chineseEnabled=true in App/fgo-launcher.json (the game reads App\\zh)")
        except (OSError, ValueError) as exc:
            print(f"  could not set chineseEnabled: {exc}")
        manifest = read_json(os.path.join(root, "manifest.json"))
        marker = {"version": manifest.get("version"),
                  "appliedUtc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                  "manifestHash": manifest.get("manifestHash")}
        marker_path = os.path.join(root, "App", "zh", "en-patch.json")
        os.makedirs(os.path.dirname(marker_path), exist_ok=True)
        with open(marker_path, "w", encoding="utf-8") as fh:
            json.dump(marker, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
        print(f"  marker: App/zh/en-patch.json (version {marker['version']})")

    print(f"mode: {mode}")
    print(f"  payload per manifest: {payload_copied}/{manifest_total - payload_separate} files"
          + (f"  (+{payload_separate} patched by patch-server.py)" if payload_separate else ""))
    print(f"  zh hook (fgozh.dll): {fgozh_state}")
    print(f"  resources overlaid:  {copied}/{len(rels)}  (backups created: {backups})")
    print(f"  strings in ago.exe:  {patched}  (skipped: {skipped}, empty translation: {empty})")
    all_problems = payload_problems + fgozh_problems + problems + exe_problems
    if all_problems:
        print(f"  problems ({len(all_problems)}):")
        for line in all_problems[:15]:
            print("    " + line)
    if mode == "plan":
        print("  nothing was changed; add --apply to apply")
    return 1 if all_problems else 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: apply-en.py <install_root> [--apply | --verify]")
        raise SystemExit(2)
    sys.exit(main())
