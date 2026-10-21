# Shake to Find Cursor — Windows

**Bring macOS's "shake the mouse and the pointer gets big" gesture to Windows 10/11.**

Lose your cursor on a 4K monitor or across three displays? Grab the mouse and wiggle it —
the pointer turns into a solid, 3× larger arrow for a moment, then shrinks back.

Windows-only, Python 3.8+, **zero dependencies** (pure `ctypes` + Win32, no `pip install`).

![preview](docs/preview.png)

<sub>Left → middle → right: normal pointer, the enlarged pointer after a shake, and back to normal ~1 second later.</sub>

---

## Why

macOS has had this since forever. Windows has "make the pointer bigger" in accessibility
settings, but that is global and permanent — it makes the cursor huge everywhere, all the time.
This tool does it *only when you ask for it*, with a shake.

## Quick start

1. Windows 10 or 11, and Python 3.8+ installed (tick **Add python.exe to PATH** during setup).
2. Download this repo (`Code → Download ZIP`) or `git clone`.
3. Double-click **`start.bat`**.
4. Shake the mouse.

No installer, no admin rights, no services. To stop it, press `Ctrl + Alt + Q` or run `stop.bat`.

| File | What it does |
| --- | --- |
| `start.bat` | Start in the background (no console window) |
| `start-debug.bat` | Start with a console window that logs every detected shake |
| `stop.bat` | Quit, and force-restore the system cursor |
| `autostart-on.bat` | Run automatically at login (current user, no admin) |
| `autostart-off.bat` | Undo the above |
| `shake_cursor.pyw` | The whole application |

## Hotkeys

| Keys | Action |
| --- | --- |
| *shake the mouse* | Enlarge the pointer |
| `Ctrl + Alt + Space` | Trigger the effect manually |
| `Ctrl + Alt + Q` | Quit |

## How the shake is detected

Not a simple distance threshold — each axis runs a small state machine that tracks **net
displacement** and counts **direction reversals**:

- a reversal only counts if the stroke before it was at least `SHAKE_MIN_RUN` (14 px) long
- you need **3 reversals within 0.6 s** (about 1.5 back-and-forth wiggles)
- in practice a deliberate shake fires in ~0.3 s

That means slow drags, drawing circles, a shaky hand or slowly swinging the mouse back and
forth **do not** trigger it.

## Configuration

Open `shake_cursor.pyw` — the constants are at the top:

| Constant | Default | Meaning |
| --- | --- | --- |
| `PEAK_SCALE` | `3.0` | How much the pointer grows |
| `GROW_SEC` | `0.13` | Grow duration |
| `HOLD_SEC` | `0.72` | How long it stays big |
| `SHRINK_SEC` | `0.26` | Shrink-back duration |
| `SHAKE_MIN_RUN` | `14` | Minimum stroke length in px — raise it to make triggering harder |
| `SHAKE_WINDOW` | `0.60` | Reversal counting window, seconds |
| `SHAKE_REVERSALS` | `3` | Reversals required inside the window |
| `HIDE_SYSTEM_CUR` | `True` | Hide the real cursor while overlaying (see below) |
| `OUTLINE_RATIO` | `0.08` | White outline thickness, relative to arrow height |

Restart the app after editing.

## How it works

1. **Detection** — polls `GetCursorPos` at ~125 Hz and feeds the deltas into two per-axis
   reversal counters (see above).
2. **Hiding the real pointer** — builds a fully transparent cursor with
   `CreateIconIndirect` and swaps the system arrow for it via `SetSystemCursor(OCR_NORMAL)`.
   Only the plain arrow is replaced; the I-beam and hand cursors are untouched.
3. **Drawing the big pointer** — a `WS_EX_LAYERED` click-through window updated with
   `UpdateLayeredWindow` (per-pixel alpha). The arrow is a polygon filled by GDI at **4×
   supersampling** and then downsampled with `StretchBlt(HALFTONE)`, so the edges stay clean
   instead of blurry. 21 sizes are pre-rendered once at startup (~30 ms); the animation only
   swaps frames and follows the mouse.
4. **Failsafe** — the realistic worst case of `SetSystemCursor` is a cursor that stays
   invisible. So the app spawns a tiny **watchdog** child process that blocks on a stdin pipe:
   if the main process exits for *any* reason (clean exit, crash, killed from Task Manager),
   the pipe closes, the watchdog calls `SystemParametersInfo(SPI_SETCURSORS)` and the pointer
   comes back. `stop.bat` is a manual override on top of that.

## Troubleshooting

**The cursor is invisible / disappeared.** Run `stop.bat`. It restores the system cursor even
if the app is not running.

**Nothing happens when I shake.** Run `start-debug.bat` and watch the console — it prints every
detected shake with its coordinates. If you only see "running" and never a trigger, shake
harder/faster, or lower `SHAKE_MIN_RUN` / `SHAKE_REVERSALS` in `shake_cursor.pyw`.

**"Python was not found".** Install Python 3.8+ from
[python.org](https://www.python.org/downloads/) with "Add python.exe to PATH" checked.

**Two copies are running?** They can't be — the app holds a named mutex and a second instance
just exits.

**After editing the code nothing changed.** The running instance still has the old code in
memory. Quit (`Ctrl + Alt + Q`) and start again.

## Known limitations

- Only the **plain arrow** cursor is replaced. When the pointer hovers a text field (I-beam) or
  a link (hand), the system cursor keeps its shape and you will see the big arrow next to it.
  This is a deliberate trade-off: it never hides what the pointer currently means.
- In exclusive-fullscreen games and in apps that draw or cache their own cursor, the overlay
  may not appear.
- Windows only. macOS already has the feature; on X11 you would want a compositor overlay.

## License

[MIT](LICENSE). Use it, fork it, ship it.

---

[中文说明 / Chinese README](README.zh-CN.md)
