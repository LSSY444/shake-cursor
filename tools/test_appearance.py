# -*- coding: utf-8 -*-
"""
Tests for the appearance feature: the renderer must actually paint the requested
colour, the frame cache must be rebuilt when the scale changes, and the tray menu
must offer both submenus with the right items checked.

    python tools/test_appearance.py
"""

import collections
import ctypes
import importlib.util
import json
import os
import sys
from ctypes import byref, c_int, string_at
from ctypes import wintypes as w

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MF_BYPOSITION = 0x00000400
MF_SEPARATOR = 0x00000800

user32 = ctypes.WinDLL("user32", use_last_error=True)
user32.GetMenuItemCount.argtypes = [w.HANDLE]
user32.GetMenuItemCount.restype = c_int
user32.GetMenuStringW.argtypes = [w.HANDLE, w.UINT, w.LPWSTR, c_int, w.UINT]
user32.GetMenuStringW.restype = c_int
user32.GetMenuItemID.argtypes = [w.HANDLE, c_int]
user32.GetMenuItemID.restype = w.UINT
user32.GetSubMenu.argtypes = [w.HANDLE, c_int]
user32.GetSubMenu.restype = w.HANDLE
user32.DestroyMenu.argtypes = [w.HANDLE]


def load_app():
    # 用临时配置, 别动用户真实的 settings.json
    os.environ.setdefault("SHAKE_CURSOR_SETTINGS",
                          os.path.join(os.environ.get("TEMP", "."), "sc_test_settings.json"))
    try:
        os.remove(os.environ["SHAKE_CURSOR_SETTINGS"])
    except OSError:
        pass
    spec = importlib.util.spec_from_file_location("sc", os.path.join(REPO, "shake_cursor.pyw"))
    m = importlib.util.module_from_spec(spec)
    sys.modules["sc"] = m
    spec.loader.exec_module(m)
    return m


def dominant_color(frame):
    """最不透明的那个颜色 —— 也就是箭头本体。"""
    n = frame.w * frame.h
    raw = string_at(frame.bits, n * 4)
    counter = collections.Counter()
    for i in range(n):
        b, g, r, a = raw[i * 4], raw[i * 4 + 1], raw[i * 4 + 2], raw[i * 4 + 3]
        if a == 255:
            counter[(r, g, b)] += 1
    return counter.most_common(1)[0] if counter else (None, 0)


def menu_items(menu):
    n = user32.GetMenuItemCount(menu)
    out = []
    for i in range(n):
        buf = ctypes.create_unicode_buffer(256)
        user32.GetMenuStringW(menu, i, buf, 256, MF_BYPOSITION)
        sub = user32.GetSubMenu(menu, i)
        out.append({"text": buf.value, "id": user32.GetMenuItemID(menu, i),
                    "sub": sub if sub else None})
    return out


def main():
    m = load_app()
    m.setup_log(False)
    ok = []

    # ---- 1. 渲染层: 指定颜色要真的画出来 ----
    for color in ((0, 0, 0), (255, 0, 0), (0x39, 0xFF, 0x14)):
        fr = m.build_frame(2.0, 1.5, color)
        got, count = dominant_color(fr)
        good = got == color and count > 100
        print("渲染 %-18s -> 主色 %-18s 像素 %5d  %s"
              % (str(color), str(got), count, "通过" if good else "失败"))
        ok.append(good)

    # ---- 2. 配置解析: 越界收敛 + 简写 hex ----
    sc = m.Scene()
    sc.settings = {"appearance": {"scale": 99, "color": "#f0a"}}
    s1, c1 = sc.appearance()
    good = s1 == 6.0 and c1 == (0xFF, 0x00, 0xAA)
    print("越界收敛 + 三位 hex -> %.1f / %s  %s" % (s1, c1, "通过" if good else "失败"))
    ok.append(good)

    sc.settings = {"appearance": {"scale": "abc", "color": "not-a-color"}}
    s2, c2 = sc.appearance()
    good = s2 == 3.0 and c2 == (0, 0, 0)
    print("坏值回退 -> %.1f / %s  %s" % (s2, c2, "通过" if good else "失败"))
    ok.append(good)

    # ---- 3. App 层: 改倍数要重建帧缓存 ----
    app = None
    try:
        app = m.App()
        before = (len(app.frames), app.frames[-1].scale)
        app.scene.set_appearance(scale=5.0, color=(0x3A, 0xA8, 0xFF))
        app.apply_appearance(preview=False)
        after = (len(app.frames), app.frames[-1].scale)
        got, count = dominant_color(app.frames[-1])
        good = (after[1] == 5.0 and after[0] != before[0] and got == (0x3A, 0xA8, 0xFF))
        print("帧重建 %s -> %s (帧数 %d->%d, 峰值帧主色 %s)  %s"
              % (before, after, before[0], after[0], got, "通过" if good else "失败"))
        ok.append(good)

        # ---- 4. 菜单里有 放大倍数 / 箭头颜色 两个子菜单 ----
        menu = app.tray.build_menu("")
        items = menu_items(menu)
        names = [i["text"] for i in items]
        size_menu = next((i["sub"] for i in items if i["text"] == "放大倍数"), None)
        color_menu = next((i["sub"] for i in items if i["text"] == "箭头颜色"), None)
        size_items = [x["text"] for x in menu_items(size_menu)] if size_menu else []
        color_items = [x["text"] for x in menu_items(color_menu)] if color_menu else []
        good = (size_menu is not None and color_menu is not None
                and "5.0 倍" in size_items and "天蓝" in color_items
                and any("自定义" in t for t in color_items))
        print("子菜单: 放大倍数%s / 箭头颜色%s" % (size_items, color_items))
        print("菜单结构 %s" % ("通过" if good else "失败"))
        print("全部项:", [n for n in names if n])
        ok.append(good)
        user32.DestroyMenu(menu)
    finally:
        if app is not None:
            app.quit()

    print("\n==== %s ====" % ("全部通过" if all(ok) else "有 %d 项失败" % ok.count(False)))
    return 0 if all(ok) else 1


if __name__ == "__main__":
    sys.exit(main())
