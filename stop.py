# -*- coding: utf-8 -*-
"""
Ask the running instance to quit, then force-restore the system mouse cursor.

Use this if the pointer ever becomes invisible: it restores the cursor even when
the app itself is not running.
"""

import ctypes
import time

user32 = ctypes.WinDLL("user32", use_last_error=True)
user32.FindWindowW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p]
user32.FindWindowW.restype = ctypes.c_void_p
user32.PostMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t]
user32.SystemParametersInfoW.argtypes = [ctypes.c_uint, ctypes.c_uint, ctypes.c_void_p, ctypes.c_uint]

SPI_SETCURSORS = 0x0057
SPIF_SENDCHANGE = 0x02
WM_CLOSE = 0x0010

hwnd = user32.FindWindowW("ShakeFindCursorWnd", None)
if hwnd:
    user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
    time.sleep(0.4)
    print("Asked the running instance to quit.")
else:
    print("No running instance found.")

user32.SystemParametersInfoW(SPI_SETCURSORS, 0, None, SPIF_SENDCHANGE)
print("System cursor restored.")
