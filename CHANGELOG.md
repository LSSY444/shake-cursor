# Changelog

All notable changes to this project are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
versioning follows [Semantic Versioning](https://semver.org/).

[English](#english) · [中文](#中文)

---

## English

### [1.2.0] — 2026-10-22

**Tray menu.** Scene settings were only reachable by hand-editing `settings.json`,
which nobody does. The app now has a notification-area icon with a native popup
menu — still zero dependencies (`Shell_NotifyIcon` + `CreatePopupMenu`).

#### Added

- **Tray icon with a menu**:
  - status line — what it is doing right now and *why* it is skipping
  - `暂停 1 小时` / `暂停（直到我恢复）`
  - `开机自启` (checkbox, reads the real registry state)
  - **`当前程序不弹：xxx.exe`** — one click adds the currently focused program to
    the blacklist; clicking again removes it. This is the "learning mode" without
    a learning UI.
  - open `settings.json` / open the log / project page / quit
- **First-run balloon** — Windows 11 tucks new tray icons into the `^` overflow,
  so a one-time tip tells people where the menu lives. Shown once, tracked by a
  `tray_hint_shown` flag in the config.
- **Explorer restart recovery** — listens for `TaskbarCreated` and re-adds the
  icon, so a crashed explorer does not make the app unreachable until reboot.
- **`tools/test_tray.py`** — headless test: builds the real menu and reads the
  item texts back through `GetMenuStringW`, then exercises the pause flag and the
  blacklist toggle. No UI is shown, so it runs anywhere.

#### Fixed

- The tray status line and tooltip reported suppression **inverted**
  (`decide()` returns `(suppress, reason)`, not `(ok, reason)`), so a normally
  working app claimed "skipped: normal". Caught by the new headless test.

#### Upgrade

Drop-in. Existing `settings.json` keeps working; `tray_hint_shown` is added on
first launch of this version.

### [1.1.0] — 2026-10-22

**Scene awareness.** The pointer no longer grows while you are gaming, watching
something fullscreen, or presenting. This was the biggest gap reported after a
week of daily use: the effect is helpful on the desktop and actively harmful in
the middle of a game, where it covers what you are aiming at.

#### Added

- **Three-layer scene detection**, evaluated only at the moment a shake has
  already been recognised — the 125 Hz polling loop is untouched:

  | Layer | Signal | Catches |
  | --- | --- | --- |
  | 1 | `SHQueryUserNotificationState` | exclusive-fullscreen D3D games, fullscreen apps, presentation mode, locked session |
  | 2 | foreground window covers a monitor | apps that never update the system state |
  | 3 | process black / white list | your own exemptions |

  Layer 1 is the interesting one: it is the same API Windows uses to decide
  whether it may interrupt you, so the OS already knows you are in a game.

- **`settings.json`** — created next to the script on first run, re-read
  automatically when it changes (no restart). Keys:

  | Key | Default | Meaning |
  | --- | --- | --- |
  | `suppress_in.d3d_fullscreen` | `true` | skip exclusive-fullscreen games |
  | `suppress_in.fullscreen_app` | `true` | skip when the foreground window fills a monitor |
  | `suppress_in.busy` | `true` | skip while the shell reports "busy" |
  | `suppress_in.presentation` | `true` | skip in presentation / projector mode |
  | `suppress_in.locked` | `true` | skip while the session is locked |
  | `process_blacklist` | `game.exe, steam.exe, …` | never fire for these |
  | `process_whitelist` | `[]` | always fire for these, even fullscreen |

- **`--why` diagnostic** — prints every signal and the final verdict, so a user
  can debug "why didn't it fire in my game" without reading the source.
- **`Ctrl + Alt + P`** — pause / resume, for situations the detection cannot
  cover (emulators, some windowed games). The pointer flashes once to confirm.
- **`tools/test_scene.py`** — integration test that creates a real borderless
  fullscreen window and a real maximized window, then asserts the verdict for
  both, through the foreground path *and* through an injected window handle.

#### Notes on the design

- **Maximized is not fullscreen.** A maximized window covers ~95 % of a
  3072×1440 screen — enough to fool a naive "covers the monitor" check. The
  heuristic requires ≥99 % coverage *and* the absence of `WS_MAXIMIZE`, so a
  maximized browser keeps the effect while a real fullscreen app does not.
- **Multi-monitor aware.** A fullscreen game on monitor A does not block the
  effect while the pointer is on monitor B — you are not inside that app.
- **Whitelist beats blacklist**, and the manual hotkey (`Ctrl+Alt+Space`)
  ignores all of this on purpose.

#### Upgrade

Drop-in replacement — no migration needed. On first launch a `settings.json`
appears next to the script with the defaults above. If you preferred the old
behaviour, set every `suppress_in.*` flag to `false`.

### [1.0.0] — 2026-10-21

First public release.

- Shake the mouse → the pointer becomes a solid 3× arrow with a white outline,
  holds ~0.7 s, then shrinks back and fades out.
- Per-axis reversal counter (3 reversals of ≥14 px inside 0.6 s) instead of a
  speed threshold, so slow drags, circles and tremors do not trigger it.
- Layered popup window + `UpdateLayeredWindow`; the arrow is GDI geometry drawn
  at 4× supersampling and downsampled, 21 sizes pre-rendered at startup.
- Transparent system cursor hides the real pointer; a watchdog child process
  restores it whenever the main process dies, for any reason.
- Portable launchers, per-user autostart helper, MIT licensed.

---

## 中文

### [1.2.0] — 2026-10-22

**托盘菜单。** 之前的场景配置只能手改 `settings.json`——没人会去改。现在有了通知区图标
和原生右键菜单，依然是零依赖（`Shell_NotifyIcon` + `CreatePopupMenu`）。

#### 新增

- **托盘图标 + 菜单**：
  - 状态行 —— 当前在做什么、**为什么跳过**
  - `暂停 1 小时` / `暂停（直到我恢复）`
  - `开机自启`（勾选状态读的是真实注册表）
  - **`当前程序不弹：xxx.exe`** —— 一键把当前前台程序加进黑名单，再点一次移除。
    这相当于"学习模式"，但不需要任何额外界面。
  - 打开 `settings.json` / 查看日志 / 项目主页 / 退出
- **首次运行气泡提示** —— Windows 11 会把新托盘图标折叠进 `^` 里，
  所以第一次启动会弹一条提示告诉用户菜单在哪（只弹一次，配置里记 `tray_hint_shown`）。
- **资源管理器重启后自动恢复图标** —— 监听 `TaskbarCreated`，explorer 崩了重建也不会让应用失联。
- **`tools/test_tray.py`** —— 无头测试：真的构建菜单并用 `GetMenuStringW` 把条目读回来核对，
  再验证暂停标记和黑名单切换；不弹任何 UI，任何环境都能跑。

#### 修复

- 托盘状态行和提示文本把"是否抑制"**写反了**（`decide()` 返回的是 `(是否抑制, 原因)`，
  不是 `(ok, 原因)`），导致一切正常时显示"跳过 · 正常"。由新增的无头测试发现。

#### 升级

直接替换。已有 `settings.json` 继续有效；本版首次启动会补上 `tray_hint_shown`。

### [1.1.0] — 2026-10-22

**场景感知。** 打游戏、全屏看片、投屏演示时，指针不再变大。

这是深度使用一周后反馈最集中的问题：在桌面上这个效果是帮忙的，但在游戏里
它是帮倒忙的——大箭头正好盖住你要瞄的地方。

#### 新增

- **三层场景判定**，只在「摇动已被识别、即将播放动画」的那一刻执行，
  125Hz 轮询主循环完全不受影响：

  | 层 | 信号 | 能识别 |
  | --- | --- | --- |
  | 1 | `SHQueryUserNotificationState` | 独占全屏 D3D 游戏、有全屏应用在跑、演示模式、锁屏 |
  | 2 | 前台窗口是否铺满显示器 | 不更新系统状态的程序 |
  | 3 | 进程黑 / 白名单 | 你自己的例外清单 |

  第 1 层是关键：这就是 Windows 判断"能不能打扰用户"用的同一个 API，
  系统本身就知道你在不在游戏里。

- **`settings.json`** —— 首次运行自动生成在脚本同目录，**修改后自动重载，不用重启**。
  配置项见上表（`suppress_in` 五项 + 黑白名单）。
- **`--why` 诊断** —— 打印全部判据和最终结论，用户可以自己查
  「我那个游戏为什么没被识别」，不用读源码。
- **`Ctrl + Alt + P`** —— 暂停 / 恢复，应对识别不了的场景（模拟器、部分窗口化游戏）。
  按一下会闪一次放大，表示收到了。
- **`tools/test_scene.py`** —— 集成测试：真的创建一个无边框全屏窗口和一个最大化窗口，
  断言两者的判定结果；前台路径和「直接注入窗口句柄」路径都测。

#### 几个设计取舍

- **最大化 ≠ 全屏。** 最大化窗口在 3072×1440 的屏上占 95%，足以骗过
  「铺满显示器」的粗暴判断。现在的判据是「覆盖率 ≥99% **且** 窗口没有
  `WS_MAXIMIZE`」——最大化的浏览器照常放大，真正的全屏应用才抑制。
- **多屏感知。** 游戏在 A 屏全屏、光标在 B 屏时照常放大，因为你人不在那个应用里。
- **白名单优先于黑名单**；手动热键 `Ctrl+Alt+Space` 故意无视以上所有规则。

#### 升级说明

直接替换即可，无需迁移。首次启动会在脚本同目录生成 `settings.json`（上面那些默认值）。
如果你更喜欢旧行为，把所有 `suppress_in.*` 设为 `false` 就行。

### [1.0.0] — 2026-10-21

首个公开版本。

- 晃鼠标 → 指针变成实心 3 倍箭头（白色描边），停留约 0.7 秒后缩回并淡出。
- 用逐轴折返计数（0.6 秒内 3 次 ≥14px 的折返）代替速度阈值，
  所以缓慢拖动、画圈、手抖都不会误触发。
- 分层窗口 + `UpdateLayeredWindow`；箭头是 GDI 几何图形在 4 倍超采样下绘制再降采样，
  21 个尺寸在启动时预渲染。
- 全透明系统光标隐藏真指针；看门狗子进程保证主进程无论怎么退出都能还原。
- 可移植启动脚本、当前用户级开机自启、MIT 协议。
