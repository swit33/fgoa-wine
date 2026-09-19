#!/usr/bin/env python3
"""Drops the robust-access request the game makes when it creates its second GL context.

Wine's EGL backend refuses a context created with WGL_CONTEXT_FLAGS_ARB = ROBUST_ACCESS
(EGL_BAD_MATCH). The game then releases its current context and tries to resolve its 280-entry
OpenGL entry-point table with none current; Wine's wglGetProcAddress answers NULL for every
OpenGL 1.2+ symbol in that state, so the load stops at the first one and the whole table stays
zero. The game calls glCreateBuffers through the table and dies on the null pointer.

Zeroing the attribute *name* at 0x27AF7D ends the attribute list there, so the context is created
without the flag and everything after that works. Note what it does not do: it does not restore
proper robustness, it removes the request for it.

Origins: found by quinnjr for the NVIDIA case and described in quinnjr/FGOAC-scooby, branch
wine-compat (patch/wine/apply-wine-fixes.py, MIT). NOT VERIFIED on this project's hardware: this
machine is AMD + Mesa, where Mesa answers the request instead of refusing it, so the crash this
patch cures does not happen here. It is applied on AMD installs as well - all it changes is a flag
the game asks for, and the game runs the same with or without it - but if a build ever misbehaves
after this patch, this is the first thing to blame.

Single 4-byte patch at file offset 0x27AF7D:

    94 20 00 00   WGL_CONTEXT_FLAGS_ARB   (what the retail executable has)
    00 00 00 00   end of the attribute list (what this writes)

  python3 patch-ago-gl.py App/ago.exe            # show what is there, change nothing
  python3 patch-ago-gl.py App/ago.exe --verify   # 0 when patched, 1 when not
  python3 patch-ago-gl.py App/ago.exe --apply    # patch it in place (idempotent)
"""
import sys

OFFSET = 0x27AF7D
WANT = bytes.fromhex("94200000")
DONE = bytes.fromhex("00000000")


def read(path):
    with open(path, "rb") as fh:
        fh.seek(OFFSET)
        return fh.read(4)


def main():
    if len(sys.argv) < 2:
        print("usage: patch-ago-gl.py <ago.exe> [--apply|--verify]")
        return 2
    path = sys.argv[1]
    try:
        current = read(path)
    except OSError as exc:
        print(f"cannot read {path}: {exc}")
        return 2

    if "--verify" in sys.argv:
        if current == DONE:
            print("robust-access request is already dropped")
            return 0
        print(f"robust-access request is still there ({current.hex()} at 0x{OFFSET:x})")
        return 1

    if current == DONE:
        print("already applied; nothing to do")
        return 0
    if current != WANT:
        print(f"unexpected bytes at 0x{OFFSET:x}: found {current.hex()}, expected {WANT.hex()}")
        print("this is not the ago.exe this patch was written for - nothing changed")
        return 1
    if "--apply" not in sys.argv:
        print(f"dry run: 0x{OFFSET:x} {WANT.hex()} -> {DONE.hex()}; add --apply")
        return 0

    with open(path, "r+b") as fh:
        fh.seek(OFFSET)
        fh.write(DONE)
    print(f"applied: 0x{OFFSET:x} {WANT.hex()} -> {DONE.hex()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
