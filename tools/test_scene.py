# -*- coding: utf-8 -*-
"""
Integration test for the scene-detection layer.

Creates a real window and asks shake_cursor.pyw what it thinks about it:
  A. borderless fullscreen covering the monitor -> must be suppressed
  B. maximized normal window (work area only)   -> must NOT be suppressed

Two paths are checked: the normal "foreground window" path and a direct handle
injection, so the result does not depend on winning the foreground lock.
"""

import ctypes
import os
import subprocess
import sys
import time
from ctypes import POINTER, Structure, byref, c_int, c_ssize_t, sizeof
from ctypes import wintypes as w

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable

WS_POPUP = 0x80000000
WS_OVERLAPPEDWINDOW = 0x00CF0000
SW_SHOW, SW_MAXIMIZE = 5, 3

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

WNDPROC = ctypes.WINFUNCTYPE(c_ssize_t, w.HWND, w.UINT, w.WPARAM, w.LPARAM)


class WNDCLASSEXW(Structure):
    _fields_ = [("cbSize", w.UINT), ("style", w.UINT), ("lpfnWndProc", WNDPROC),
                ("cbClsExtra", c_int), ("cbWndExtra", c_int),
                ("hInstance", w.HANDLE), ("hIcon", w.HANDLE), ("hCursor", w.HANDLE),
                ("hbrBackground", w.HANDLE), ("lpszMenuName", w.LPCWSTR),
                ("lpszClassName", w.LPCWSTR), ("hIconSm", w.HANDLE)]


class MSG(Structure):
    _fields_ = [("hwnd", w.HWND), ("message", w.UINT), ("wParam", w.WPARAM),
                ("lParam", w.LPARAM), ("time", w.DWORD), ("pt", w.POINT)]


def proto():
    user32.DefWindowProcW.argtypes = [w.HWND, w.UINT, w.WPARAM, c_ssize_t]
    user32.DefWindowProcW.restype = c_ssize_t
    user32.CreateWindowExW.argtypes = [w.DWORD, w.LPCWSTR, w.LPCWSTR, w.DWORD,
                                       c_int, c_int, c_int, c_int,
                                       w.HWND, w.HANDLE, w.HANDLE, w.LPVOID]
    user32.CreateWindowExW.restype = w.HWND
    user32.RegisterClassExW.argtypes = [POINTER(WNDCLASSEXW)]
    user32.RegisterClassExW.restype = w.ATOM
    user32.ShowWindow.argtypes = [w.HWND, c_int]
    user32.SetForegroundWindow.argtypes = [w.HWND]
    user32.BringWindowToTop.argtypes = [w.HWND]
    user32.AttachThreadInput.argtypes = [w.DWORD, w.DWORD, w.BOOL]
    user32.GetWindowThreadProcessId.argtypes = [w.HWND, w.LPDWORD]
    user32.GetForegroundWindow.restype = w.HWND
    user32.GetSystemMetrics.argtypes = [c_int]
    user32.DestroyWindow.argtypes = [w.HWND]
    user32.PeekMessageW.argtypes = [POINTER(MSG), w.HWND, w.UINT, w.UINT, w.UINT]
    user32.TranslateMessage.argtypes = [POINTER(MSG)]
    user32.DispatchMessageW.argtypes = [POINTER(MSG)]
    kernel32.GetModuleHandleW.restype = w.HANDLE
    kernel32.GetCurrentThreadId.restype = w.DWORD


_KEEP = []


def _proc(h, m, wp, lp):
    return int(user32.DefWindowProcW(h, m, wp, int(lp)))


def pump(seconds):
    msg = MSG()
    end = time.perf_counter() + seconds
    while time.perf_counter() < end:
        while user32.PeekMessageW(byref(msg), None, 0, 0, 1):
            user32.TranslateMessage(byref(msg))
            user32.DispatchMessageW(byref(msg))
        time.sleep(0.01)


def make_window(popup):
    hinst = kernel32.GetModuleHandleW(None)
    cls = "SceneTestWnd_%d_%d" % (popup, int(time.time() * 1000) % 100000)
    cb = WNDPROC(_proc)
    _KEEP.append(cb)
    wc = WNDCLASSEXW()
    wc.cbSize = sizeof(WNDCLASSEXW)
    wc.lpfnWndProc = cb
    wc.hInstance = hinst
    wc.lpszClassName = cls
    _KEEP.append(wc)
    if not user32.RegisterClassExW(byref(wc)):
        raise SystemExit("RegisterClassExW 失败: %d" % ctypes.get_last_error())

    sw, sh = user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
    if popup:
        hwnd = user32.CreateWindowExW(0, cls, "fullscreen-test", WS_POPUP,
                                      0, 0, sw, sh, None, None, hinst, None)
        user32.ShowWindow(hwnd, SW_SHOW)
    else:
        hwnd = user32.CreateWindowExW(0, cls, "maximized-test", WS_OVERLAPPEDWINDOW,
                                      100, 100, 800, 600, None, None, hinst, None)
        user32.ShowWindow(hwnd, SW_MAXIMIZE)
    if not hwnd:
        raise SystemExit("CreateWindowExW 失败: %d" % ctypes.get_last_error())

    fg = user32.GetForegroundWindow()
    fg_tid = user32.GetWindowThreadProcessId(fg, None)
    my_tid = kernel32.GetCurrentThreadId()
    user32.AttachThreadInput(my_tid, fg_tid, True)
    user32.SetForegroundWindow(hwnd)
    user32.BringWindowToTop(hwnd)
    user32.AttachThreadInput(my_tid, fg_tid, False)
    pump(0.9)
    return hwnd, user32.GetForegroundWindow() == hwnd


def ask_fg():
    p = subprocess.run([PY, "-X", "utf8", "shake_cursor.pyw", "--why"],
                       cwd=REPO, capture_output=True, text=True, timeout=40)
    return p.stdout + p.stderr


def ask_handle(hwnd):
    code = "\n".join([
        "import importlib.util,sys,ctypes",
        "spec=importlib.util.spec_from_file_location('sc',r'" + REPO + chr(92) + "shake_cursor.pyw')",
        "m=importlib.util.module_from_spec(spec)",
        "sys.modules['sc']=m",
        "spec.loader.exec_module(m)",
        "s=m.Scene()",
        "i=s.snapshot((100,100),hwnd=ctypes.c_void_p(" + str(hwnd) + "))",
        "print('FULLSCREEN=' + str(i['fullscreen']))",
        "print('CLASS=' + str(i['cls']))",
        "r=i['rect']",
        "print('RECT=' + ('None' if not r else str((r.right-r.left, r.bottom-r.top))))",
    ])
    p = subprocess.run([PY, "-X", "utf8", "-c", code], cwd=REPO,
                       capture_output=True, text=True, timeout=40)
    return (p.stdout + p.stderr).strip()


def brief(out):
    keys = ("前台窗口:", "  类名", "  标题", "系统勿扰状态:", "前台窗口全屏:", "结论:")
    return "\n".join(l for l in out.splitlines() if l.startswith(keys))


def main():
    proto()
    rows = []
    for popup, label, want in ((True, "全屏窗口", True), (False, "最大化窗口", False)):
        hwnd, got_fg = make_window(popup)
        try:
            fg_out = brief(ask_fg())
            handle_out = ask_handle(hwnd)
            fs = "FULLSCREEN=True" in handle_out
            ok_handle = (fs == want)
            ok_fg = None
            if got_fg:
                ok_fg = ("不放大" in fg_out) == want
            print("=== %s (前台=%s) ===" % (label, got_fg))
            print("  [注入 hwnd] %s" % handle_out.replace("\n", "  "))
            if got_fg:
                print("  [前台路径] %s" % fg_out.replace("\n", " | "))
            print("  期望 fullscreen=%s -> 注入路径%s%s\n"
                  % (want, "通过" if ok_handle else "失败",
                     "" if ok_fg is None else (" / 前台路径" + ("通过" if ok_fg else "失败"))))
            rows.append((label, ok_handle, ok_fg))
        finally:
            user32.DestroyWindow(hwnd)
            pump(0.3)

    print("==== 汇总 ====")
    for label, ok_h, ok_f in rows:
        print("  %-10s 注入路径:%s%s"
              % (label, "通过" if ok_h else "失败",
                 "" if ok_f is None else "  前台路径:" + ("通过" if ok_f else "失败")))
    return 0 if all(r[1] and (r[2] is None or r[2]) for r in rows) else 1


if __name__ == "__main__":
    sys.exit(main())
