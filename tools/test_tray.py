# -*- coding: utf-8 -*-
"""
Headless test for the tray menu: builds the menu without showing it, reads the
item texts back through GetMenuStringW, and exercises the commands that the menu
dispatches (pause, blacklist toggle). No UI is displayed, so it can run anywhere.

    python tools/test_tray.py
"""

import ctypes
import importlib.util
import os
import sys
from ctypes import POINTER, byref, c_int, c_ssize_t
from ctypes import wintypes as w

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MF_BYPOSITION = 0x00000400
MF_SEPARATOR = 0x00000800

user32 = ctypes.WinDLL("user32", use_last_error=True)
user32.GetMenuStringW.argtypes = [w.HANDLE, w.UINT, w.LPWSTR, c_int, w.UINT]
user32.GetMenuStringW.restype = c_int
user32.GetMenuItemCount.argtypes = [w.HANDLE]
user32.GetMenuItemCount.restype = c_int
user32.GetMenuState.argtypes = [w.HANDLE, w.UINT, w.UINT]
user32.GetMenuState.restype = w.UINT
user32.GetMenuItemID.argtypes = [w.HANDLE, c_int]
user32.GetMenuItemID.restype = w.UINT
user32.DestroyMenu.argtypes = [w.HANDLE]


def load_app():
    spec = importlib.util.spec_from_file_location("sc", os.path.join(REPO, "shake_cursor.pyw"))
    m = importlib.util.module_from_spec(spec)
    sys.modules["sc"] = m
    spec.loader.exec_module(m)
    return m


def dump(menu):
    rows = []
    n = user32.GetMenuItemCount(menu)
    for i in range(n):
        state = user32.GetMenuState(menu, i, MF_BYPOSITION)
        if state & MF_SEPARATOR:
            rows.append(("", "---", ""))
            continue
        buf = ctypes.create_unicode_buffer(256)
        user32.GetMenuStringW(menu, i, buf, 256, MF_BYPOSITION)
        gid = user32.GetMenuItemID(menu, i)
        rows.append((buf.value, "gray" if state & 0x0001 else "ok",
                     "checked" if state & 0x0008 else ""))
    return rows


def main():
    m = load_app()
    m.setup_log(verbose=True)
    app = None
    try:
        app = m.App()
        tray = app.tray
        print("托盘图标: %s" % ("已创建" if tray.added else "创建失败"))
        assert tray.added, "托盘图标没有挂上"

        menu = tray.build_menu("chrome.exe")
        print("\n--- 菜单（目标是 chrome.exe）---")
        for text, state, extra in dump(menu):
            print("  %-34s %-5s %s" % (text, state, extra))
        user32.DestroyMenu(menu)

        # 黑名单来回切换
        before = list(app.scene._blacklist)
        r1 = app.scene.toggle_blacklist("test_game.exe")
        ok1 = (r1 is True and "test_game.exe" in app.scene._blacklist)
        r2 = app.scene.toggle_blacklist("test_game.exe")
        ok2 = (r2 is False and "test_game.exe" not in app.scene._blacklist)
        ok3 = list(app.scene._blacklist) == before
        print("\n黑名单切换: 加入=%s 移除=%s 复原=%s" % (ok1, ok2, ok3))

        # 暂停状态要体现在菜单上
        app.pause_for(1.0)
        menu2 = tray.build_menu("")
        rows = dump(menu2)
        paused = any("已暂停" in t for t, _, _ in rows)
        user32.DestroyMenu(menu2)
        print("暂停后菜单显示“已暂停”: %s" % paused)
        print("托盘提示文本:", tray.tooltip())

        app.pause_until = 0.0                     # 立即使暂停过期
        app.scene.paused = False
        app.scene._cache_t = -1.0

        checks = [tray.added, ok1, ok2, ok3, paused]
        print("\n==== %s ====" % ("全部通过" if all(checks) else "有用例失败"))
        return 0 if all(checks) else 1
    finally:
        if app is not None:
            app.quit()


if __name__ == "__main__":
    sys.exit(main())
