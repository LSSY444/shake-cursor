# -*- coding: utf-8 -*-
"""
摇一摇找鼠标 (Shake to Find Cursor) for Windows
================================================
模仿 macOS 的「晃鼠标 → 指针变大变实心 → 恢复」效果。

原理:
  1. 125Hz 轮询鼠标坐标, 用状态机识别左右/上下快速往返(摇动);
  2. 摇动确认后, 用 SetSystemCursor 把系统箭头指针临时换成全透明指针(隐去真指针);
  3. 再叠加一个 layered 窗口, 用 UpdateLayeredWindow 画出放大版箭头(带白描边,
     4x 超采样抗锯齿), 做 放大 -> 停留 -> 缩回并淡出 的动画;
  4. 动画结束还原系统指针。子进程看门狗保证主进程异常退出时指针一定会被还原。

纯 ctypes + 标准库, 无第三方依赖。
热键: Ctrl+Alt+Q 退出     Ctrl+Alt+Space 手动演示一次
"""

import atexit
import ctypes
import json
import logging
import math
import os
import signal
import subprocess
import sys
import time
from ctypes import (POINTER, Structure, byref, c_int, c_ssize_t, c_ubyte, c_uint,
                    c_ulonglong, c_void_p, memmove, sizeof, string_at)
from ctypes import wintypes as w

# ============================ 可调参数 ============================
__version__       = "1.1.0"   # 1.1.0: 场景感知(游戏/全屏/演示时不响应)
PEAK_SCALE        = 3.0    # 峰值放大倍数
GROW_SEC          = 0.13   # 放大耗时(秒)
HOLD_SEC          = 0.72   # 保持最大时长(秒)
SHRINK_SEC        = 0.26   # 缩回耗时(秒)
SHAKE_MIN_RUN     = 14     # 单程最小位移(像素), 越大越不灵敏
SHAKE_WINDOW      = 0.60   # 摇动时间窗(秒)
SHAKE_REVERSALS   = 3      # 窗口内需要的折返次数(3 次 ≈ 来回晃 1.5 下)
POLL_SEC          = 0.008  # 鼠标采样间隔
HIDE_SYSTEM_CUR   = True   # 是否隐藏系统原指针(False 会看到小箭头叠在大箭头里)
OUTLINE_RATIO     = 0.08   # 白色描边宽度 / 箭头高度
LOG_TO_FILE       = True

APP_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_PATH = os.path.join(APP_DIR, "shake_cursor.log")
WATCHDOG_FLAG = "--watchdog"

# ============================ Win32 声明 ============================
user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
shell32 = ctypes.WinDLL("shell32", use_last_error=True)
dwmapi = ctypes.WinDLL("dwmapi", use_last_error=True)

WS_POPUP = 0x80000000
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOPMOST = 0x00000008
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_NOACTIVATE = 0x08000000
SW_HIDE = 0
SW_SHOWNOACTIVATE = 4
ULW_ALPHA = 0x00000002
AC_SRC_OVER = 0x00
AC_SRC_ALPHA = 0x01
SRCCOPY = 0x00CC0020
BLACKNESS = 0x00000042
HALFTONE = 4
NULL_PEN = 8
PS_SOLID = 0
PS_NULL = 5
ALTERNATE = 1
SPI_SETCURSORS = 0x0057
SPIF_SENDCHANGE = 0x02
OCR_NORMAL = 32512
DIB_RGB_COLORS = 0
PM_REMOVE = 0x0001
WM_QUIT = 0x0012
WM_DESTROY = 0x0002
WM_HOTKEY = 0x0312
WM_ENDSESSION = 0x0016
WM_CLOSE = 0x0010
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_NOREPEAT = 0x4000
LOGPIXELSY = 90
CREATE_NO_WINDOW = 0x08000000
DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = -4

# 经典 Windows 箭头形状, 热点在 (0,0), 外框 12 x 20
ARROW = [(0.0, 0.0), (0.0, 17.0), (4.0, 13.0), (7.0, 20.0),
         (10.0, 18.0), (7.0, 12.0), (12.0, 12.0)]
ARROW_W, ARROW_H = 12.0, 20.0
SS = 4  # 超采样倍率


class BITMAPINFOHEADER(Structure):
    _fields_ = [("biSize", w.DWORD), ("biWidth", ctypes.c_long), ("biHeight", ctypes.c_long),
                ("biPlanes", w.WORD), ("biBitCount", w.WORD), ("biCompression", w.DWORD),
                ("biSizeImage", w.DWORD), ("biXPelsPerMeter", ctypes.c_long),
                ("biYPelsPerMeter", ctypes.c_long), ("biClrUsed", w.DWORD),
                ("biClrImportant", w.DWORD)]


class BITMAPINFO(Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", w.DWORD * 3)]


class BLENDFUNCTION(Structure):
    _fields_ = [("BlendOp", c_ubyte), ("BlendFlags", c_ubyte),
                ("SourceConstantAlpha", c_ubyte), ("AlphaFormat", c_ubyte)]


class ICONINFO(Structure):
    _fields_ = [("fIcon", w.BOOL), ("xHotspot", w.DWORD), ("yHotspot", w.DWORD),
                ("hbmMask", w.HBITMAP), ("hbmColor", w.HBITMAP)]


WNDPROC = ctypes.WINFUNCTYPE(c_ssize_t, w.HWND, w.UINT, w.WPARAM, w.LPARAM)


class WNDCLASSEXW(Structure):
    _fields_ = [("cbSize", w.UINT), ("style", w.UINT), ("lpfnWndProc", WNDPROC),
                ("cbClsExtra", c_int), ("cbWndExtra", c_int), ("hInstance", w.HINSTANCE),
                ("hIcon", w.HICON), ("hCursor", w.HANDLE), ("hbrBackground", w.HBRUSH),
                ("lpszMenuName", w.LPCWSTR), ("lpszClassName", w.LPCWSTR),
                ("hIconSm", w.HICON)]


class MSG(Structure):
    _fields_ = [("hwnd", w.HWND), ("message", w.UINT), ("wParam", w.WPARAM),
                ("lParam", w.LPARAM), ("time", w.DWORD), ("pt", w.POINT)]


def _proto():
    P = ctypes.POINTER
    user32.GetCursorPos.argtypes = [P(w.POINT)]
    user32.GetCursorPos.restype = w.BOOL
    user32.SetCursorPos.argtypes = [c_int, c_int]
    user32.CreateWindowExW.argtypes = [w.DWORD, w.LPCWSTR, w.LPCWSTR, w.DWORD,
                                       c_int, c_int, c_int, c_int, w.HWND, w.HMENU,
                                       w.HINSTANCE, w.LPVOID]
    user32.CreateWindowExW.restype = w.HWND
    user32.DefWindowProcW.argtypes = [w.HWND, w.UINT, w.WPARAM, w.LPARAM]
    user32.DefWindowProcW.restype = c_ssize_t
    user32.RegisterClassExW.argtypes = [P(WNDCLASSEXW)]
    user32.RegisterClassExW.restype = w.ATOM
    user32.UpdateLayeredWindow.argtypes = [w.HWND, w.HDC, P(w.POINT), P(w.SIZE), w.HDC,
                                           P(w.POINT), w.DWORD, P(BLENDFUNCTION), w.DWORD]
    user32.UpdateLayeredWindow.restype = w.BOOL
    user32.ShowWindow.argtypes = [w.HWND, c_int]
    user32.ShowWindow.restype = w.BOOL
    user32.PeekMessageW.argtypes = [P(MSG), w.HWND, w.UINT, w.UINT, w.UINT]
    user32.PeekMessageW.restype = w.BOOL
    user32.DispatchMessageW.argtypes = [P(MSG)]
    user32.DispatchMessageW.restype = c_ssize_t
    user32.TranslateMessage.argtypes = [P(MSG)]
    user32.RegisterHotKey.argtypes = [w.HWND, c_int, w.UINT, w.UINT]
    user32.RegisterHotKey.restype = w.BOOL
    user32.SystemParametersInfoW.argtypes = [w.UINT, w.UINT, w.LPVOID, w.UINT]
    user32.SystemParametersInfoW.restype = w.BOOL
    user32.SetSystemCursor.argtypes = [w.HANDLE, w.DWORD]
    user32.SetSystemCursor.restype = w.BOOL
    user32.CreateIconIndirect.argtypes = [P(ICONINFO)]
    user32.CreateIconIndirect.restype = w.HANDLE
    user32.GetDC.argtypes = [w.HWND]
    user32.GetDC.restype = w.HDC
    user32.ReleaseDC.argtypes = [w.HWND, w.HDC]
    user32.GetSystemMetrics.argtypes = [c_int]
    user32.GetSystemMetrics.restype = c_int
    user32.DestroyCursor.argtypes = [w.HANDLE]
    user32.DestroyCursor.restype = w.BOOL
    user32.DestroyWindow.argtypes = [w.HWND]
    user32.PostQuitMessage.argtypes = [c_int]

    gdi32.CreateCompatibleDC.argtypes = [w.HDC]
    gdi32.CreateCompatibleDC.restype = w.HDC
    gdi32.CreateDIBSection.argtypes = [w.HDC, P(BITMAPINFO), w.UINT, P(c_void_p), w.HANDLE, w.DWORD]
    gdi32.CreateDIBSection.restype = w.HBITMAP
    gdi32.SelectObject.argtypes = [w.HDC, w.HGDIOBJ]
    gdi32.SelectObject.restype = w.HGDIOBJ
    gdi32.DeleteObject.argtypes = [w.HGDIOBJ]
    gdi32.DeleteObject.restype = w.BOOL
    gdi32.DeleteDC.argtypes = [w.HDC]
    gdi32.DeleteDC.restype = w.BOOL
    gdi32.CreateSolidBrush.argtypes = [w.DWORD]
    gdi32.CreateSolidBrush.restype = w.HBRUSH
    gdi32.CreatePen.argtypes = [c_int, c_int, w.DWORD]
    gdi32.CreatePen.restype = w.HPEN
    gdi32.GetStockObject.argtypes = [c_int]
    gdi32.GetStockObject.restype = w.HGDIOBJ
    gdi32.Polygon.argtypes = [w.HDC, P(w.POINT), c_int]
    gdi32.Polygon.restype = w.BOOL
    gdi32.SetPolyFillMode.argtypes = [w.HDC, c_int]
    gdi32.SetPolyFillMode.restype = c_int
    gdi32.PatBlt.argtypes = [w.HDC, c_int, c_int, c_int, c_int, w.DWORD]
    gdi32.PatBlt.restype = w.BOOL
    gdi32.SetStretchBltMode.argtypes = [w.HDC, c_int]
    gdi32.SetStretchBltMode.restype = c_int
    gdi32.SetBrushOrgEx.argtypes = [w.HDC, c_int, c_int, P(w.POINT)]
    gdi32.SetBrushOrgEx.restype = w.BOOL
    gdi32.StretchBlt.argtypes = [w.HDC, c_int, c_int, c_int, c_int, w.HDC,
                                 c_int, c_int, c_int, c_int, w.DWORD]
    gdi32.StretchBlt.restype = w.BOOL
    gdi32.CreateBitmap.argtypes = [c_int, c_int, w.UINT, w.UINT, c_void_p]
    gdi32.CreateBitmap.restype = w.HBITMAP
    gdi32.GdiFlush.argtypes = []
    gdi32.GetDeviceCaps.argtypes = [w.HDC, c_int]
    gdi32.GetDeviceCaps.restype = c_int

    kernel32.GetModuleHandleW.argtypes = [w.LPCWSTR]
    kernel32.GetModuleHandleW.restype = c_void_p
    kernel32.CreateMutexW.argtypes = [c_void_p, w.BOOL, w.LPCWSTR]
    kernel32.CreateMutexW.restype = c_void_p


_proto()


def dpi_aware():
    try:
        fn = user32.SetProcessDpiAwarenessContext
        fn.argtypes = [c_void_p]
        fn.restype = w.BOOL
        if fn(c_void_p(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2)):
            return "pmv2"
    except Exception:
        pass
    try:
        if user32.SetProcessDPIAware():
            return "system"
    except Exception:
        pass
    return "none"


def get_dpi():
    try:
        fn = user32.GetDpiForSystem
        fn.restype = w.UINT
        v = fn()
        if v:
            return v / 96.0
    except Exception:
        pass
    hdc = user32.GetDC(None)
    try:
        v = gdi32.GetDeviceCaps(hdc, LOGPIXELSY)
    finally:
        user32.ReleaseDC(None, hdc)
    return (v or 96) / 96.0


# ============================ 位图绘制 ============================
class Frame:
    """一帧预渲染好的放大指针位图。"""
    __slots__ = ("scale", "w", "h", "hdc", "hbmp", "bits", "margin")

    def __init__(self, scale, w, h, hdc, hbmp, bits, margin):
        self.scale, self.w, self.h = scale, w, h
        self.hdc, self.hbmp, self.bits, self.margin = hdc, hbmp, bits, margin


def _make_dib(width, height):
    bmi = BITMAPINFO()
    hdr = bmi.bmiHeader
    hdr.biSize = sizeof(BITMAPINFOHEADER)
    hdr.biWidth = width
    hdr.biHeight = -height          # 负数 = 自上而下
    hdr.biPlanes = 1
    hdr.biBitCount = 32
    hdr.biCompression = 0           # BI_RGB
    bits = c_void_p()
    hdc = gdi32.CreateCompatibleDC(None)
    hbmp = gdi32.CreateDIBSection(hdc, byref(bmi), DIB_RGB_COLORS, byref(bits), None, 0)
    if not hdc or not hbmp:
        raise OSError("CreateDIBSection 失败")
    gdi32.SelectObject(hdc, hbmp)
    return hdc, hbmp, bits


def _fill_poly(hdc, pts, box_w, box_h, color, pen_w=0):
    gdi32.PatBlt(hdc, 0, 0, box_w, box_h, BLACKNESS)
    arr = (w.POINT * len(pts))(*[w.POINT(int(round(x)), int(round(y))) for x, y in pts])
    brush = gdi32.CreateSolidBrush(color)
    if pen_w > 0:
        pen = gdi32.CreatePen(PS_SOLID, max(1, int(round(pen_w))), color)
    else:
        pen = gdi32.GetStockObject(NULL_PEN)
    old_b = gdi32.SelectObject(hdc, brush)
    old_p = gdi32.SelectObject(hdc, pen)
    gdi32.SetPolyFillMode(hdc, ALTERNATE)
    gdi32.Polygon(hdc, arr, len(pts))
    gdi32.GdiFlush()
    gdi32.SelectObject(hdc, old_b)
    gdi32.SelectObject(hdc, old_p)
    gdi32.DeleteObject(brush)
    if pen_w > 0:
        gdi32.DeleteObject(pen)


def _down(src_hdc, sw, sh, dst_hdc, dw, dh):
    gdi32.SetStretchBltMode(dst_hdc, HALFTONE)
    gdi32.SetBrushOrgEx(dst_hdc, 0, 0, None)
    gdi32.StretchBlt(dst_hdc, 0, 0, dw, dh, src_hdc, 0, 0, sw, sh, SRCCOPY)
    gdi32.GdiFlush()


def build_frame(scale, dpi):
    """渲染 scale 倍大小的指针: 黑色实心 + 白色描边, 预乘 alpha。"""
    unit = scale * dpi
    outline = max(1.0, OUTLINE_RATIO * ARROW_H * unit)
    margin = int(math.ceil(outline)) + 2
    fw = int(math.ceil(ARROW_W * unit)) + margin * 2
    fh = int(math.ceil(ARROW_H * unit)) + margin * 2
    ssw, ssh = fw * SS, fh * SS

    def to_ss(pts):
        return [((x * unit + margin) * SS, (y * unit + margin) * SS) for x, y in pts]

    pts_ss = to_ss(ARROW)
    white = 0x00FFFFFF

    hdc_a, hbmp_a, _ = _make_dib(ssw, ssh)   # 白色层(箭头 + 外描边)
    hdc_b, hbmp_b, _ = _make_dib(ssw, ssh)   # 黑色层(箭头实心)
    hdc_t1, hbmp_t1, bits_t1 = _make_dib(fw, fh)
    hdc_t2, hbmp_t2, bits_t2 = _make_dib(fw, fh)
    hdc_o, hbmp_o, bits_o = _make_dib(fw, fh)
    try:
        _fill_poly(hdc_a, pts_ss, ssw, ssh, white, pen_w=2.0 * outline * SS)
        _fill_poly(hdc_b, pts_ss, ssw, ssh, white, pen_w=0)
        _down(hdc_a, ssw, ssh, hdc_t1, fw, fh)
        _down(hdc_b, ssw, ssh, hdc_t2, fw, fh)

        n = fw * fh
        a = string_at(bits_t1, n * 4)
        b = string_at(bits_t2, n * 4)
        out = bytearray(n * 4)
        for i in range(n):
            cov_a = a[i * 4]          # 白层覆盖度(蓝通道即亮度)
            cov_b = b[i * 4]          # 黑层覆盖度
            # 黑层叠在白层之上: premul = 255 * cov_a * (1 - cov_b)
            premul = (cov_a * (255 - cov_b)) // 255
            alpha = cov_b + premul           # alpha = cov_b + cov_a*(1-cov_b)
            o = i * 4
            out[o] = premul
            out[o + 1] = premul
            out[o + 2] = premul
            out[o + 3] = alpha
        memmove(bits_o, bytes(out), len(out))
        gdi32.GdiFlush()
    finally:
        for hdc, hbmp in ((hdc_a, hbmp_a), (hdc_b, hbmp_b),
                          (hdc_t1, hbmp_t1), (hdc_t2, hbmp_t2)):
            gdi32.DeleteObject(hbmp)
            gdi32.DeleteDC(hdc)
    return Frame(scale, fw, fh, hdc_o, hbmp_o, bits_o, margin)


# ============================ 摇动识别 ============================
class AxisShake:
    """单轴折返计数: 只有振幅足够大的反向才算一次折返。"""

    def __init__(self, min_run):
        self.min_run = min_run
        self.dir = 0
        self.acc = 0.0
        self.peak = 0.0
        self.revs = []

    def feed(self, t, delta):
        if self.dir == 0:
            if abs(delta) >= 1.0:
                self.dir = 1 if delta > 0 else -1
                self.acc = abs(delta)
                self.peak = self.acc
            return False
        if (delta > 0) == (self.dir > 0):
            self.acc += abs(delta)
            if self.acc > self.peak:
                self.peak = self.acc
            return False
        self.acc -= abs(delta)
        if self.acc > 0:
            return False
        # 反向足够深 -> 记一次折返
        rev = False
        if self.peak >= self.min_run:
            self.revs.append(t)
            rev = True
        self.dir = -self.dir
        self.acc = -self.acc if self.acc < 0 else 0.0
        self.peak = self.acc
        self.revs = [x for x in self.revs if t - x <= SHAKE_WINDOW]
        return rev

    def hit(self):
        return len(self.revs) >= SHAKE_REVERSALS

    def reset(self):
        self.revs = []
        self.dir = 0
        self.acc = self.peak = 0.0


# ============================ 指针隐藏 / 还原 ============================
def restore_system_cursor():
    try:
        user32.SystemParametersInfoW(SPI_SETCURSORS, 0, None, SPIF_SENDCHANGE)
        return True
    except Exception:
        return False


class CursorHider:
    def __init__(self, enabled=True):
        self.enabled = enabled
        self.active = False

    def hide(self):
        if not self.enabled or self.active:
            return False
        try:
            row = 4  # 32bpp 1bit -> 每行 4 字节
            mask_bits = ctypes.create_string_buffer(b"\xff" * (row * 32), row * 32)
            color_bits = ctypes.create_string_buffer(b"\x00" * (row * 32), row * 32)
            hbm_mask = gdi32.CreateBitmap(32, 32, 1, 1, mask_bits)
            hbm_color = gdi32.CreateBitmap(32, 32, 1, 1, color_bits)
            if not hbm_mask or not hbm_color:
                return False
            ii = ICONINFO(1, 0, 0, hbm_mask, hbm_color)
            hcur = user32.CreateIconIndirect(byref(ii))
            hbm_mask and gdi32.DeleteObject(hbm_mask)
            hbm_color and gdi32.DeleteObject(hbm_color)
            if not hcur:
                return False
            if not user32.SetSystemCursor(hcur, OCR_NORMAL):
                user32.DestroyCursor(hcur)
                return False
            self.active = True
            return True
        except Exception:
            logging.warning("隐藏系统指针失败, 退化为叠加显示", exc_info=True)
            self.enabled = False
            return False

    def restore(self):
        if not self.active:
            return
        restore_system_cursor()
        self.active = False


# ============================ 动画 ============================
def _ease_out_cubic(x):
    return 1.0 - (1.0 - x) ** 3


def _ease_in_out(x):
    return x * x * (3.0 - 2.0 * x)



# ============================ 场景感知 ============================
# 打游戏 / 全屏看片 / 演示投影 时不该把指针变大, 否则挡住视野还抢注意力。
# 三层信号, 从最准到兜底:
#   1. SHQueryUserNotificationState —— Windows 自己的"勿扰"状态(它就是靠这个压制通知的);
#   2. 前台窗口是否铺满光标所在的那块显示器(兜底, 有些程序不更新系统状态);
#   3. 进程黑白名单(用户可控, 白名单优先级最高)。
SETTINGS_PATH = os.path.join(APP_DIR, "settings.json")

DEFAULT_SETTINGS = {
    "suppress_in": {
        "d3d_fullscreen": True,     # 独占全屏 D3D 应用(游戏)
        "fullscreen_app": True,     # 前台全屏窗口(全屏视频 / 浏览器全屏 / 无边框全屏游戏)
        "busy": True,               # 系统忙(全屏应用运行中或已应用演示设置)
        "presentation": True,       # 演示 / 投影模式
        "locked": True,             # 锁屏 / 用户不在
    },
    "process_blacklist": [
        "game.exe", "steam.exe", "steamwebhelper.exe", "obs64.exe", "mstsc.exe",
    ],
    "process_whitelist": [],
    "log_suppressed": True,
}

QUNS_TEXT = {
    1: "用户不在/锁屏",
    2: "全屏应用运行中或演示设置",
    3: "独占全屏 D3D 应用",
    4: "演示模式",
    5: "正常(可接收通知)",
    6: "静默时段",
    7: "应用模式",
}
# 这些类名是桌面/任务栏, 覆盖全屏也不算"应用全屏"
GWL_STYLE = -16
WS_MAXIMIZE = 0x01000000

DESKTOP_CLASSES = {"Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd",
                   "TaskListThumbnailWnd", "ForegroundStaging"}


class MONITORINFO(Structure):
    _fields_ = [("cbSize", w.DWORD), ("rcMonitor", w.RECT),
                ("rcWork", w.RECT), ("dwFlags", w.DWORD)]


_SCENE_PROTO_DONE = False


def _proto_scene():
    global _SCENE_PROTO_DONE
    if _SCENE_PROTO_DONE:
        return
    _SCENE_PROTO_DONE = True
    shell32.SHQueryUserNotificationState.argtypes = [POINTER(c_int)]
    shell32.SHQueryUserNotificationState.restype = ctypes.c_long
    user32.GetForegroundWindow.restype = w.HWND
    user32.GetWindowRect.argtypes = [w.HWND, POINTER(w.RECT)]
    user32.GetClassNameW.argtypes = [w.HWND, w.LPWSTR, c_int]
    user32.GetWindowTextW.argtypes = [w.HWND, w.LPWSTR, c_int]
    user32.GetWindowThreadProcessId.argtypes = [w.HWND, POINTER(w.DWORD)]
    user32.IsIconic.argtypes = [w.HWND]
    user32.GetWindowLongW.argtypes = [w.HWND, c_int]
    user32.GetWindowLongW.restype = ctypes.c_long
    user32.IsWindowVisible.argtypes = [w.HWND]
    user32.MonitorFromWindow.argtypes = [w.HWND, w.DWORD]
    user32.MonitorFromWindow.restype = w.HMONITOR
    user32.MonitorFromPoint.argtypes = [w.POINT, w.DWORD]
    user32.MonitorFromPoint.restype = w.HMONITOR
    user32.GetMonitorInfoW.argtypes = [w.HMONITOR, POINTER(MONITORINFO)]
    user32.GetMonitorInfoW.restype = w.BOOL
    kernel32.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
    kernel32.OpenProcess.restype = w.HANDLE
    kernel32.QueryFullProcessImageNameW.argtypes = [w.HANDLE, w.DWORD, w.LPWSTR,
                                                    POINTER(w.DWORD)]
    kernel32.CloseHandle.argtypes = [w.HANDLE]
    dwmapi.DwmGetWindowAttribute.argtypes = [w.HWND, w.DWORD, c_void_p, w.DWORD]
    dwmapi.DwmGetWindowAttribute.restype = ctypes.c_long


def query_user_state():
    """SHQueryUserNotificationState: 5 = 正常, 其余都表示"别打扰用户"。"""
    try:
        v = c_int(0)
        if shell32.SHQueryUserNotificationState(byref(v)) == 0:
            return v.value
    except Exception:
        logging.debug("SHQueryUserNotificationState 失败", exc_info=True)
    return 5


def window_class(hwnd):
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buf, 256)
    return buf.value


def window_title(hwnd):
    buf = ctypes.create_unicode_buffer(512)
    user32.GetWindowTextW(hwnd, buf, 512)
    return buf.value


def window_process(hwnd):
    pid = w.DWORD(0)
    user32.GetWindowThreadProcessId(hwnd, byref(pid))
    if not pid.value:
        return ""
    h = kernel32.OpenProcess(0x1000, False, pid.value)   # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return ""
    try:
        size = w.DWORD(1024)
        buf = ctypes.create_unicode_buffer(1024)
        if kernel32.QueryFullProcessImageNameW(h, 0, buf, byref(size)):
            return os.path.basename(buf.value)
    finally:
        kernel32.CloseHandle(h)
    return ""


def window_rect(hwnd):
    """优先用 DWM 的可见边框, 它对全屏窗口比 GetWindowRect 更准。"""
    r = w.RECT()
    if dwmapi.DwmGetWindowAttribute(hwnd, 9, byref(r), sizeof(r)) != 0:   # DWMWA_EXTENDED_FRAME_BOUNDS
        if not user32.GetWindowRect(hwnd, byref(r)):
            return None
    return r


def monitor_info(hm):
    mi = MONITORINFO()
    mi.cbSize = sizeof(MONITORINFO)
    if not user32.GetMonitorInfoW(hm, byref(mi)):
        return None
    return mi


def covers_monitor(rect, mi, ratio=0.99):
    if rect is None or mi is None:
        return False
    mr = mi.rcMonitor
    x0 = max(rect.left, mr.left)
    y0 = max(rect.top, mr.top)
    x1 = min(rect.right, mr.right)
    y1 = min(rect.bottom, mr.bottom)
    if x1 <= x0 or y1 <= y0:
        return False
    inter = (x1 - x0) * (y1 - y0)
    total = max(1, (mr.right - mr.left) * (mr.bottom - mr.top))
    return inter / float(total) >= ratio


class Scene:
    """判断"现在该不该放大指针"。只在摇动被识别后才查询, 热路径零开销。"""

    CACHE_SEC = 0.25

    def __init__(self):
        _proto_scene()
        self.settings = dict(DEFAULT_SETTINGS)
        self._suppress = dict(DEFAULT_SETTINGS["suppress_in"])
        self._blacklist = []
        self._whitelist = []
        self._mtime = None
        self._cache_t = -1.0
        self._cache = (False, "")
        self._last_log = {}
        self.paused = False
        self.reload(force=True)

    # ---------- 配置 ----------
    def reload(self, force=False):
        try:
            mt = os.path.getmtime(SETTINGS_PATH)
        except OSError:
            mt = None
        if not force and mt == self._mtime:
            return
        self._mtime = mt
        data = {}
        if mt is not None:
            try:
                with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                logging.warning("settings.json 解析失败, 使用默认配置", exc_info=True)
                data = {}
        else:
            self._write_default()
        sup = dict(DEFAULT_SETTINGS["suppress_in"])
        sup.update({k: bool(v) for k, v in (data.get("suppress_in") or {}).items()
                    if k in sup})
        self._suppress = sup
        self._blacklist = [str(x).strip().lower()
                           for x in (data.get("process_blacklist")
                                     or DEFAULT_SETTINGS["process_blacklist"]) if str(x).strip()]
        self._whitelist = [str(x).strip().lower()
                           for x in (data.get("process_whitelist") or []) if str(x).strip()]
        self.settings = data
        logging.info("场景配置已载入: 抑制=%s 黑名单=%d 白名单=%d",
                     {k: v for k, v in sup.items() if v}, len(self._blacklist),
                     len(self._whitelist))

    def _write_default(self):
        try:
            with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
                json.dump(DEFAULT_SETTINGS, f, ensure_ascii=False, indent=2)
            logging.info("已生成默认配置 %s", SETTINGS_PATH)
        except Exception:
            logging.warning("写入默认配置失败(不影响运行)", exc_info=True)

    # ---------- 采样 ----------
    def snapshot(self, pos=None, hwnd=None):
        """hwnd=None 时取前台窗口; 传值则直接分析该窗口(测试/诊断用)。"""
        _proto_scene()
        if hwnd is None:
            hwnd = user32.GetForegroundWindow()
        info = {"hwnd": hwnd or 0, "cls": "", "title": "", "process": "",
                "quns": query_user_state(), "fullscreen": False,
                "fs_monitor": None, "cur_monitor": None, "same_monitor": None,
                "rect": None, "mon": None}
        if pos:
            info["cur_monitor"] = user32.MonitorFromPoint(w.POINT(pos[0], pos[1]), 2)
        if hwnd:
            info["cls"] = window_class(hwnd)
            info["title"] = window_title(hwnd)
            info["process"] = window_process(hwnd)
            style = user32.GetWindowLongW(hwnd, GWL_STYLE) or 0
            # 最大化 ≠ 全屏: 它只铺满工作区, 底下还有任务栏
            maximized = bool(style & WS_MAXIMIZE)
            if info["cls"] not in DESKTOP_CLASSES and user32.IsWindowVisible(hwnd) \
                    and not user32.IsIconic(hwnd) and not maximized:
                hm = user32.MonitorFromWindow(hwnd, 2)      # MONITOR_DEFAULTTONEAREST
                mi = monitor_info(hm)
                rect = window_rect(hwnd)
                if covers_monitor(rect, mi):
                    info["fullscreen"] = True
                    info["fs_monitor"] = hm
                    info["rect"] = rect
                    info["mon"] = mi
            if info["fullscreen"] and info["cur_monitor"]:
                info["same_monitor"] = (info["cur_monitor"] == info["fs_monitor"])
        return info

    # ---------- 判定 ----------
    def decide(self, pos=None, use_cache=True):
        now = time.perf_counter()
        if use_cache and now - self._cache_t < self.CACHE_SEC:
            return self._cache

        self.reload()
        if self.paused:
            result = (True, "已暂停(Ctrl+Alt+P)")
        else:
            snap = self.snapshot(pos)
            exe = (snap["process"] or "").lower()
            sup = self._suppress
            if exe and exe in self._whitelist:
                result = (False, "白名单进程: " + exe)
            elif exe and exe in self._blacklist:
                result = (True, "黑名单进程: " + exe)
            elif snap["quns"] == 3 and sup["d3d_fullscreen"]:
                result = (True, "独占全屏游戏 (D3D)")
            elif snap["quns"] == 4 and sup["presentation"]:
                result = (True, "演示/投影模式")
            elif snap["quns"] == 2 and sup["busy"]:
                result = (True, "全屏应用运行中")
            elif snap["quns"] == 1 and sup["locked"]:
                result = (True, "锁屏/用户不在")
            elif snap["fullscreen"] and sup["fullscreen_app"]:
                if snap["same_monitor"] is False:
                    result = (False, "全屏窗口在另一块屏, 光标不在那里")
                else:
                    r = snap["rect"]
                    result = (True, "前台全屏窗口 %dx%d" % (r.right - r.left, r.bottom - r.top))
            else:
                result = (False, "正常")
        self._cache_t = now
        self._cache = result
        return result

    def allows(self, pos=None):
        suppress, reason = self.decide(pos)
        if suppress and self._suppress_log_enabled():
            self._log_throttled(reason)
        return not suppress

    def _suppress_log_enabled(self):
        sup = (self.settings.get("log_suppressed") if self.settings else None)
        return True if sup is None else bool(sup)

    def _log_throttled(self, reason):
        now = time.perf_counter()
        last = self._last_log.get(reason, 0.0)
        if now - last > 5.0:
            self._last_log[reason] = now
            logging.info("跳过放大: %s", reason)

    def toggle_pause(self):
        self.paused = not self.paused
        self._cache_t = -1.0
        logging.info("已%s (Ctrl+Alt+P)", "暂停" if self.paused else "恢复")
        return self.paused


def scene_report():
    """--why: 把判定依据全部打印出来, 方便用户自查"为什么游戏里还是弹"。"""
    _proto_scene()
    sc = Scene()
    cx = user32.GetSystemMetrics(0) // 2
    cy = user32.GetSystemMetrics(1) // 2
    snap = sc.snapshot((cx, cy))
    ok, reason = sc.decide((cx, cy), use_cache=False)

    lines = []
    lines.append("shake-cursor v%s  场景判定报告" % __version__)
    lines.append("配置文件: %s" % SETTINGS_PATH)
    lines.append("  %s" % ("(不存在, 已按默认生成)" if sc._mtime is None else "(已载入)"))
    lines.append("")
    lines.append("前台窗口: 0x%08X" % (snap["hwnd"] or 0))
    lines.append("  类名   : %s" % (snap["cls"] or "-"))
    lines.append("  标题   : %s" % ((snap["title"] or "-")[:60]))
    lines.append("  进程   : %s" % (snap["process"] or "-"))
    lines.append("")
    q = snap["quns"]
    lines.append("系统勿扰状态: %d (%s)" % (q, QUNS_TEXT.get(q, "未知")))
    for key, label in (("d3d_fullscreen", "独占全屏 D3D 视为场景"),
                       ("fullscreen_app", "全屏窗口视为场景"),
                       ("busy", "系统忙视为场景"),
                       ("presentation", "演示模式视为场景")):
        lines.append("  %-16s : %s" % (label, "开" if sc._suppress.get(key) else "关"))
    lines.append("")
    lines.append("前台窗口全屏: %s" % ("是" if snap["fullscreen"] else "否"))
    if snap["fullscreen"]:
        r = snap["rect"]
        lines.append("  窗口矩形 : (%d,%d)-(%d,%d)  %dx%d"
                     % (r.left, r.top, r.right, r.bottom, r.right - r.left, r.bottom - r.top))
        lines.append("  光标同屏 : %s" % {True: "是", False: "否", None: "未知"}[snap["same_monitor"]])
    lines.append("")
    lines.append("黑白名单: 黑 %s | 白 %s"
                 % (", ".join(sc._blacklist) or "空", ", ".join(sc._whitelist) or "空"))
    if sc.paused:
        lines.append("暂停状态: 已暂停(Ctrl+Alt+P)")
    lines.append("")
    lines.append("结论: %s —— %s" % ("不放大" if ok else "正常放大", reason))
    out = "\n".join(lines)
    print(out)
    logging.info("--why 报告:\n%s", out)
    return 0


class App:
    CLASS_NAME = "ShakeFindCursorWnd"

    def __init__(self):
        self.running = True
        dpi_aware()                 # 必须在建窗口/取坐标之前声明, 否则 150% 缩放下坐标错位
        self.dpi = get_dpi()
        self.frames = []
        self.anim_t0 = None
        self.anim_total = GROW_SEC + HOLD_SEC + SHRINK_SEC
        self.detectors = [AxisShake(SHAKE_MIN_RUN), AxisShake(SHAKE_MIN_RUN)]
        self.last_trigger = 0.0
        self.last_pos = None
        self.hider = CursorHider(HIDE_SYSTEM_CUR)
        self.scene = Scene()
        self.hwnd = None
        self._wndproc_ref = WNDPROC(self._wndproc)
        self._msg = MSG()
        self._last_frame = None
        self._build_frames()
        self._create_window()

    # ---------- 预渲染 ----------
    def _build_frames(self):
        steps = max(2, int(round((PEAK_SCALE - 1.0) / 0.1)) + 1)
        t0 = time.perf_counter()
        for i in range(steps):
            s = 1.0 + (PEAK_SCALE - 1.0) * i / (steps - 1)
            self.frames.append(build_frame(s, self.dpi))
        logging.info("预渲染 %d 帧, 耗时 %.0f ms, dpi=%.2f",
                     len(self.frames), (time.perf_counter() - t0) * 1000, self.dpi)

    def _frame_for(self, scale):
        best = self.frames[0]
        for f in self.frames:
            if abs(f.scale - scale) < abs(best.scale - scale):
                best = f
        return best

    # ---------- 窗口 ----------
    def _wndproc(self, hwnd, msg, wp, lp):
        if msg == WM_HOTKEY:
            if wp == 1:
                self.quit()
            elif wp == 2:
                self.trigger(force=True)
            elif wp == 3:
                self.scene.toggle_pause()
                self.trigger(force=True)      # 用一次放大作为"收到了"的反馈
            return 0
        if msg in (WM_DESTROY, WM_ENDSESSION):
            self.hider.restore()
            self.running = False
            user32.PostQuitMessage(0)
            return 0
        if msg == WM_CLOSE:
            self.quit()
            return 0
        return user32.DefWindowProcW(hwnd, msg, wp, lp)

    def _create_window(self):
        hinst = kernel32.GetModuleHandleW(None)
        hinst = c_void_p(hinst) if hinst else None
        wc = WNDCLASSEXW()
        wc.cbSize = sizeof(WNDCLASSEXW)
        wc.style = 0
        wc.lpfnWndProc = self._wndproc_ref
        wc.hInstance = hinst
        wc.lpszClassName = self.CLASS_NAME
        user32.RegisterClassExW(byref(wc))
        ex = WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOPMOST | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE
        self.hwnd = user32.CreateWindowExW(ex, self.CLASS_NAME, "shake-find-cursor",
                                           WS_POPUP, 0, 0, 16, 16, None, None, hinst, None)
        if not self.hwnd:
            raise OSError("创建窗口失败: %d" % ctypes.get_last_error())
        if not user32.RegisterHotKey(self.hwnd, 1, MOD_CONTROL | MOD_ALT | MOD_NOREPEAT, ord("Q")):
            logging.warning("热键 Ctrl+Alt+Q 注册失败(可能被其它程序占用)")
        if not user32.RegisterHotKey(self.hwnd, 2, MOD_CONTROL | MOD_ALT | MOD_NOREPEAT, 0x20):
            logging.warning("热键 Ctrl+Alt+Space 注册失败(可能被其它程序占用)")
        if not user32.RegisterHotKey(self.hwnd, 3, MOD_CONTROL | MOD_ALT | MOD_NOREPEAT, ord("P")):
            logging.warning("热键 Ctrl+Alt+P 注册失败(可能被其它程序占用)")

    # ---------- 绘制 ----------
    def _paint(self, frame, x, y, alpha):
        dst = w.POINT(x - frame.margin, y - frame.margin)
        size = w.SIZE(frame.w, frame.h)
        src = w.POINT(0, 0)
        bf = BLENDFUNCTION(AC_SRC_OVER, 0, max(0, min(255, alpha)), AC_SRC_ALPHA)
        user32.UpdateLayeredWindow(self.hwnd, None, byref(dst), byref(size),
                                   frame.hdc, byref(src), 0, byref(bf), ULW_ALPHA)

    def _cursor_pos(self):
        pt = w.POINT()
        if not user32.GetCursorPos(byref(pt)):
            return None
        return pt.x, pt.y

    # ---------- 触发与结束 ----------
    def trigger(self, force=False):
        now = time.perf_counter()
        if not force and (self.anim_t0 or now - self.last_trigger < 0.9):
            return
        if self.anim_t0:
            return
        pos = self._cursor_pos()
        if not pos:
            return
        # 打游戏 / 全屏看片 / 演示投影 时不弹; 手动热键(force)不受限制
        if not force and not self.scene.allows(pos):
            self.detectors[0].reset()
            self.detectors[1].reset()
            return
        self.last_trigger = now
        self.anim_t0 = now
        self.detectors[0].reset()
        self.detectors[1].reset()
        self.hider.hide()
        user32.ShowWindow(self.hwnd, SW_SHOWNOACTIVATE)
        logging.info("触发: 位置 %s", pos)

    def _tick(self, now):
        if self.anim_t0 is None:
            return
        el = now - self.anim_t0
        pos = self._cursor_pos()
        if pos is None:
            pos = self.last_pos or (0, 0)
        self.last_pos = pos
        x, y = pos

        if el < GROW_SEC:
            k = _ease_out_cubic(el / GROW_SEC)
            scale = 1.0 + (PEAK_SCALE - 1.0) * k
            alpha = 255
        elif el < GROW_SEC + HOLD_SEC:
            scale = PEAK_SCALE
            alpha = 255
        elif el < self.anim_total:
            k = (el - GROW_SEC - HOLD_SEC) / SHRINK_SEC
            scale = PEAK_SCALE + (1.0 - PEAK_SCALE) * _ease_in_out(k)
            fade = max(0.0, (k - 0.5) / 0.5)
            alpha = int(255 * (1.0 - fade))
        else:
            self._finish()
            return
        frame = self._frame_for(scale)
        self._last_frame = frame
        self._paint(frame, x, y, alpha)

    def _finish(self):
        self.anim_t0 = None
        self.hider.restore()        # 先还原真指针, 再隐藏叠加层, 避免出现"指针消失一帧"
        user32.ShowWindow(self.hwnd, SW_HIDE)

    def quit(self):
        self._finish()
        self.hider.restore()
        self.running = False
        user32.PostQuitMessage(0)

    # ---------- 主循环 ----------
    def run(self):
        msg = self._msg
        prev = None
        next_anim_tick = 0.0
        while self.running:
            while user32.PeekMessageW(byref(msg), None, 0, 0, PM_REMOVE):
                user32.TranslateMessage(byref(msg))
                user32.DispatchMessageW(byref(msg))
                if not self.running:
                    break
            now = time.perf_counter()
            pos = self._cursor_pos()
            if pos:
                if self.anim_t0 is None and prev is not None:
                    dx, dy = pos[0] - prev[0], pos[1] - prev[1]
                    rx = self.detectors[0].feed(now, dx)
                    ry = self.detectors[1].feed(now, dy)
                    if (rx or ry) and (self.detectors[0].hit() or self.detectors[1].hit()):
                        self.trigger()
                prev = pos
            if self.anim_t0 is not None:
                if now >= next_anim_tick:
                    self._tick(now)
                    next_anim_tick = now + 1.0 / 60.0
            time.sleep(POLL_SEC)


# ============================ 看门狗 ============================
def spawn_watchdog():
    """子进程守着 stdin 管道; 主进程不论怎么死, 管道关闭后它都会还原指针。"""
    try:
        exe = sys.executable
        if not exe.lower().endswith("pythonw.exe"):
            cand = os.path.join(os.path.dirname(exe), "pythonw.exe")
            if os.path.exists(cand):
                exe = cand
        creation = CREATE_NO_WINDOW
        p = subprocess.Popen([exe, os.path.abspath(__file__), WATCHDOG_FLAG],
                             stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, creationflags=creation,
                             close_fds=True)
        logging.info("看门狗已启动 pid=%s", p.pid)
        return p
    except Exception:
        logging.warning("看门狗启动失败(不影响主功能)", exc_info=True)
        return None


def watchdog_main():
    note("看门狗启动 pid=%d, 等待主进程" % os.getpid())
    try:
        sys.stdin.buffer.read()          # 主进程死掉(管道关闭)前一直阻塞
    except Exception:
        pass
    restore_system_cursor()
    note("检测到主进程已退出 -> 已还原系统鼠标指针")
    return 0


def note(msg):
    """看门狗专用日志(不复用 logging, 避免和主进程抢同一个文件)。"""
    try:
        with open(os.path.join(APP_DIR, "watchdog.log"), "a", encoding="utf-8") as f:
            f.write("%s %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg))
    except Exception:
        pass


_WATCHDOG = None


# ============================ 入口 ============================
def setup_log(verbose):
    handlers = []
    if LOG_TO_FILE:
        try:
            handlers.append(logging.FileHandler(LOG_PATH, mode="w", encoding="utf-8"))
        except Exception:
            pass
    if verbose and sys.stdout is not None:
        handlers.append(logging.StreamHandler(sys.stdout))
    logging.basicConfig(level=logging.INFO, handlers=handlers,
                        format="%(asctime)s %(levelname)s %(message)s")


_MUTEX = None


def single_instance():
    """已有实例在跑就直接退出, 避免两个实例互相抢指针。"""
    global _MUTEX
    ctypes.set_last_error(0)                     # 先清掉残留错误码, 避免误判"已存在"
    _MUTEX = kernel32.CreateMutexW(None, False, "Local\\ShakeFindCursor_SingleInstance")
    return ctypes.get_last_error() != 183        # ERROR_ALREADY_EXISTS


def preview(hold_sec=8.0):
    """把指针放到屏幕中央, 直接把最大的一帧画出来, 便于截图验证。"""
    app = App()
    cx = user32.GetSystemMetrics(0) // 2
    cy = user32.GetSystemMetrics(1) // 2
    user32.SetCursorPos(cx, cy)
    app.hider.hide()
    user32.ShowWindow(app.hwnd, SW_SHOWNOACTIVATE)
    frame = app.frames[-1]
    app._paint(frame, cx, cy, 255)
    logging.info("preview 显示峰值帧 %dx%d @ (%d,%d)", frame.w, frame.h, cx, cy)
    t_end = time.perf_counter() + hold_sec
    msg = MSG()
    while time.perf_counter() < t_end:
        while user32.PeekMessageW(byref(msg), None, 0, 0, PM_REMOVE):
            user32.TranslateMessage(byref(msg))
            user32.DispatchMessageW(byref(msg))
        time.sleep(0.02)
    app._finish()
    app.hider.restore()
    logging.info("preview 结束")
    return 0


def selftest(seconds=3.0):
    """启动 -> 触发一次动画 -> 退出, 验证整条链路。"""
    app = App()
    cx = user32.GetSystemMetrics(0) // 2
    cy = user32.GetSystemMetrics(1) // 2
    user32.SetCursorPos(cx, cy)
    logging.info("selftest 开始")
    app.trigger(force=True)
    t_end = time.perf_counter() + seconds
    msg = MSG()
    while time.perf_counter() < t_end:
        while user32.PeekMessageW(byref(msg), None, 0, 0, PM_REMOVE):
            user32.TranslateMessage(byref(msg))
            user32.DispatchMessageW(byref(msg))
        app._tick(time.perf_counter())
        time.sleep(0.008)
    app.quit()
    logging.info("selftest 结束, 指针已还原")
    return 0


def main():
    if WATCHDOG_FLAG in sys.argv:
        return watchdog_main()

    setup_log(verbose="--console" in sys.argv)
    atexit.register(restore_system_cursor)
    try:
        signal.signal(signal.SIGINT, lambda *_: sys.exit(0))
    except Exception:
        pass

    if "--why" in sys.argv:
        return scene_report()
    if "--selftest" in sys.argv:
        return selftest()
    if "--preview" in sys.argv:
        return preview()
    if "--watchdog-only" in sys.argv:
        return watchdog_main()

    if not single_instance():
        logging.info("已有实例在运行, 本实例退出")
        return 0

    global _WATCHDOG
    _WATCHDOG = spawn_watchdog()      # 必须保留引用, 否则 Popen 被回收 -> 管道关闭 -> 看门狗提前退出
    app = App()
    logging.info("运行中 pid=%d: 晃动鼠标试试 | Ctrl+Alt+Space 演示 | Ctrl+Alt+P 暂停/恢复 | Ctrl+Alt+Q 退出", os.getpid())
    logging.info("场景感知: 全屏/游戏/演示时自动不响应; 配置见 settings.json")
    try:
        app.run()
    finally:
        app.hider.restore()
        restore_system_cursor()
        logging.info("已退出, 指针已还原")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
