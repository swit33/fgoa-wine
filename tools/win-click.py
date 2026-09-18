#!/usr/bin/env python3
"""Клик по окну Wine-приложения — для автоматизации лончера.

Компоновщик (Hyprland) в Wine-окно клики не доносит: `hl.dsp.send_shortcut` с mouse:272
событие отправляет, но WPF его не видит. Поэтому кликаем изнутри: скрипт запускается их же
Windows-питоном внутри Wine, где SetCursorPos + mouse_event дают настоящий клик.

Координаты — относительно КЛИЕНТСКОЙ области окна (то, что видно под заголовком).

  wine python.exe tools/win-click.py info  "FGOAC scooby"
  wine python.exe tools/win-click.py click "FGOAC scooby" 55 140
"""
import ctypes
import sys
import time

user32 = ctypes.windll.user32


class RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


def find(title):
    hwnd = user32.FindWindowW(None, title)
    if not hwnd:
        sys.exit(f"окно не найдено по заголовку: {title!r}")
    return hwnd


def geometry(hwnd):
    win, client = RECT(), RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(win))
    user32.GetClientRect(hwnd, ctypes.byref(client))
    return win, client


def info(title):
    hwnd = find(title)
    win, client = geometry(hwnd)
    print(f"hwnd={hwnd} window={win.right - win.left}x{win.bottom - win.top} "
          f"client={client.right - client.left}x{client.bottom - client.top} "
          f"titlebar={(win.bottom - win.top) - (client.bottom - client.top)}")
    return 0


def click(title, x, y):
    hwnd = find(title)
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.3)
    point = POINT(int(x), int(y))
    user32.ClientToScreen(hwnd, ctypes.byref(point))
    # WPF надёжнее реагирует, если перед нажатием было движение мыши:
    # ставим курсор, дёргаем его на пиксель туда-обратно и только потом жмём.
    # Заходим на элемент издалека: WPF ждёт MouseMove на другой элемент, затем на этот
    user32.SetCursorPos(point.x - 60, point.y - 40)
    time.sleep(0.25)
    user32.SetCursorPos(point.x, point.y)
    time.sleep(0.25)
    user32.mouse_event(0x0001, 2, 0, 0, 0)
    user32.mouse_event(0x0001, -2, 0, 0, 0)
    time.sleep(0.25)
    user32.mouse_event(0x0002, 0, 0, 0, 0)      # LEFTDOWN
    time.sleep(0.08)
    user32.mouse_event(0x0004, 0, 0, 0, 0)      # LEFTUP
    print(f"click client({x},{y}) -> screen({point.x},{point.y})")
    return 0


def move(title, x, y):
    hwnd = find(title)
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.3)
    point = POINT(int(x), int(y))
    user32.ClientToScreen(hwnd, ctypes.byref(point))
    user32.SetCursorPos(point.x, point.y)
    time.sleep(0.2)
    user32.mouse_event(0x0001, 1, 0, 0, 0)
    user32.mouse_event(0x0001, -1, 0, 0, 0)
    print(f"move client({x},{y}) -> screen({point.x},{point.y})")
    return 0


def key(name):
    """Отправить нажатие клавиши внутрь Wine (keybd_event). name: Enter, Space, F1 ..."""
    vk = {"enter": 0x0D, "space": 0x20, "f1": 0x70, "f2": 0x71, "esc": 0x1B}.get(name.lower())
    if vk is None:
        sys.exit(f"неизвестная клавиша: {name}")
    user32.keybd_event(vk, 0, 0, 0)
    time.sleep(0.06)
    user32.keybd_event(vk, 0, 2, 0)
    print(f"key {name} (vk=0x{vk:02X})")
    return 0


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    action, title = sys.argv[1], sys.argv[2]
    if action == "info":
        return info(title)
    if action == "key" and len(sys.argv) >= 3:
        return key(sys.argv[2])
    if action in ("click", "move") and len(sys.argv) >= 5:
        fn = click if action == "click" else move
        return fn(title, int(sys.argv[3]), int(sys.argv[4]))
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
