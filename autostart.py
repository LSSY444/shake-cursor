# -*- coding: utf-8 -*-
"""
Run-at-login switch for the current user.

    python autostart.py on       # add   HKCU\\...\\Run\\ShakeFindCursor
    python autostart.py off      # remove it
    python autostart.py status   # print current state

Writing to HKCU needs no administrator rights, and the entry is launched with
pythonw.exe so nothing flashes on screen at login.
"""

import os
import sys
import winreg

KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
NAME = "ShakeFindCursor"
APP_DIR = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(APP_DIR, "shake_cursor.pyw")


def pythonw():
    """pythonw.exe next to the interpreter that is running this script."""
    exe = sys.executable
    if not exe.lower().endswith("pythonw.exe"):
        cand = os.path.join(os.path.dirname(exe), "pythonw.exe")
        if os.path.exists(cand):
            exe = cand
    return exe


def command():
    return '"%s" -X utf8 "%s"' % (pythonw(), SCRIPT)


def enable():
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, KEY, 0, winreg.KEY_SET_VALUE) as k:
        winreg.SetValueEx(k, NAME, 0, winreg.REG_SZ, command())


def disable():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, KEY, 0, winreg.KEY_SET_VALUE) as k:
            winreg.DeleteValue(k, NAME)
        return True
    except OSError:
        return False


def current():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, KEY) as k:
            return winreg.QueryValueEx(k, NAME)[0]
    except OSError:
        return None


def main():
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:
        pass
    act = sys.argv[1].lower() if len(sys.argv) > 1 else "status"

    if act in ("on", "enable", "1"):
        enable()
        print("Autostart enabled.")
        print("Command: " + command())
        print("It will start on your next Windows login.")
        print("(Use start.bat if you want it running right now.)")
        return 0

    if act in ("off", "disable", "0"):
        print("Autostart disabled." if disable() else "Autostart was not enabled.")
        return 0

    value = current()
    if value:
        print("Autostart: ON")
        print("Command: " + value)
        if not os.path.exists(SCRIPT):
            print("WARNING: script not found -> " + SCRIPT)
            print("The project folder was moved or deleted; run autostart-on.bat again.")
    else:
        print("Autostart: OFF")
    return 0


if __name__ == "__main__":
    sys.exit(main())
