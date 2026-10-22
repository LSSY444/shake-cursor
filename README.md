# Shake to Find Cursor — Windows

**Bring macOS's "shake the mouse and the pointer gets big" gesture to Windows 10/11.**

Lose your cursor on a 4K monitor or across three displays? Grab the mouse and wiggle it —
the pointer turns into a solid, 3× larger arrow for a moment, then shrinks back.

Windows-only, Python 3.8+, **zero dependencies** (pure `ctypes` + Win32, no `pip install`).

![demo](docs/demo.gif)

<sub>Shake the mouse → the pointer becomes a solid 3× arrow → it shrinks back about a second later.</sub>

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
| `Ctrl + Alt + P` | Pause / resume (for things the app can't detect) |
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
| `PEAK_SCALE` | `3.0` | Default growth factor (overridden by `appearance.scale`) |
| `GROW_SEC` | `0.13` | Grow duration |
| `HOLD_SEC` | `0.72` | How long it stays big |
| `SHRINK_SEC` | `0.26` | Shrink-back duration |
| `SHAKE_MIN_RUN` | `14` | Minimum stroke length in px — raise it to make triggering harder |
| `SHAKE_WINDOW` | `0.60` | Reversal counting window, seconds |
| `SHAKE_REVERSALS` | `3` | Reversals required inside the window |
| `HIDE_SYSTEM_CUR` | `True` | Hide the real cursor while overlaying (see below) |
| `OUTLINE_RATIO` | `0.08` | White outline thickness, relative to arrow height |

Restart the app after editing.

## Updating

Replace `shake_cursor.pyw` (or `git pull`). A running instance notices the file
changed, waits 1.5 s for it to settle, launches a fresh process that waits for the
old one to exit, then quits — so the new code takes effect without restarting
anything by hand. `settings.json` is never touched by an update.

## Tray menu

The icon lives in the notification area (Windows 11 hides new icons under the **^**
chevron — drag it onto the taskbar if you want it always visible). Right-click it:

| Item | What it does |
| --- | --- |
| status line | what the app is doing right now, and *why* it is skipping |
| 暂停 1 小时 / 暂停（直到我恢复） | pause without touching the config |
| 开机自启 | toggle the per-user run-at-login entry |
| 当前程序不弹：xxx.exe | add the **currently focused program** to the blacklist with one click — no JSON editing |
| 放大倍数 | 1.5× – 5× presets, applied instantly |
| 箭头颜色 | black / white / neon green / amber / sky blue / magenta, plus **自定义…** which opens the native Windows colour picker |
| 打开设置文件 / 查看日志 | straight into `settings.json` / the log |
| 关于 / GitHub | project page |

Left double-click replays the effect. All of it is native `Shell_NotifyIcon` +
a popup menu, so the zero-dependency promise still holds.

### Appearance

Both knobs also live in `settings.json`, so they survive restarts and can be
scripted:

```json
"appearance": { "scale": 3.0, "color": "#000000" }
```

`scale` is clamped to 1.5–6.0. Changing either value re-renders the frame cache
(~40–160 ms (21–41 frames, bigger scale = more frames and bigger bitmaps)) and flashes the pointer once so you can
see the result. The arrow keeps its white outline regardless of the fill colour,
so a dark arrow stays readable on a dark background.

## Scene awareness

Enlarging the pointer is the *last* thing you want mid-game, during a fullscreen
video, or while presenting. Three layers are checked — but only at the moment a
shake has already been detected, so the 125 Hz polling loop stays untouched:

| Layer | Signal | What it catches |
| --- | --- | --- |
| 1 | `SHQueryUserNotificationState` | the API Windows itself uses to suppress notifications: `QUNS_RUNNING_D3D_FULL_SCREEN` = exclusive-fullscreen game, `QUNS_BUSY` = fullscreen app, `QUNS_PRESENTATION_MODE` = presenting |
| 2 | foreground window covers a monitor | fallback for apps that don't update the system state; **maximized windows are excluded** (they only fill the work area) |
| 3 | process black / white list | your own exemptions |

Multi-monitor detail: if the fullscreen window sits on monitor A while the pointer
is on monitor B, the effect still fires — you are not "inside" the fullscreen app.

Configure it in `settings.json` (created next to the script on first run):

| Key | Default | Meaning |
| --- | --- | --- |
| `suppress_in.d3d_fullscreen` | `true` | skip exclusive-fullscreen games |
| `suppress_in.fullscreen_app` | `true` | skip when the foreground window fills a monitor |
| `suppress_in.busy` | `true` | skip while the shell reports "busy" (covers fullscreen video) |
| `suppress_in.presentation` | `true` | skip in presentation / projector mode |
| `suppress_in.locked` | `true` | skip while the session is locked |
| `process_blacklist` | `game.exe, steam.exe, …` | never fire for these executables |
| `process_whitelist` | `[]` | always fire for these, even fullscreen |

The file is re-read when it changes — no restart needed. Whitelist beats blacklist.

### "Why didn't it fire?"

```bash
python shake_cursor.pyw --why
```

prints every signal plus the verdict, so you can debug a game it failed to detect:

```
前台窗口: 0x001E028E
  类名   : Chrome_WidgetWin_1
  进程   : chrome.exe
系统勿扰状态: 2 (全屏应用运行中或演示设置)
前台窗口全屏: 是
结论: 不放大 —— 全屏应用运行中
```

To switch the whole thing off temporarily: `Ctrl + Alt + P` (it flashes the
pointer once so you can see it took effect).

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

Release notes: [CHANGELOG.md](CHANGELOG.md) · Design notes, architecture and pitfalls: [docs/PROJECT.md](docs/PROJECT.md) (中文)

---

[中文说明 / Chinese README](README.zh-CN.md)
