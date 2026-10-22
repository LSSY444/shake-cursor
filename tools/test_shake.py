# -*- coding: utf-8 -*-
"""
摇动识别的回归测试：用合成轨迹喂给判定状态机，覆盖鼠标和触控板两种输入节奏。

    python tools/test_shake.py

触控板的关键差异：一次滑动后会抬手指，中间有 150-300ms 没有任何位移事件。
如果时间窗按"墙上时间"算，这段停顿会把窗口吃掉，导致真人滑了四下也攒不满折返次数。
"""

import importlib.util
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STEP = 0.008          # 主循环 125Hz


def load_app():
    os.environ.setdefault("SHAKE_CURSOR_SETTINGS",
                          os.path.join(os.environ.get("TEMP", "."), "sc_test_settings.json"))
    spec = importlib.util.spec_from_file_location("sc", os.path.join(REPO, "shake_cursor.pyw"))
    m = importlib.util.module_from_spec(spec)
    sys.modules["sc"] = m
    spec.loader.exec_module(m)
    return m


# ---------------------------------------------------------------- 轨迹构造
def swipe(dur, dist, curve="ease"):
    """一次滑动：在 dur 秒内沿一个方向移动 dist 像素（返回逐步位移）。"""
    n = max(1, int(round(dur / STEP)))
    out = []
    prev = 0.0
    for i in range(n):
        k = (i + 1) / n
        if curve == "ease":                      # 起手慢, 中段快, 收手慢(手指滑动像这样)
            p = k * k * (3 - 2 * k)
        elif curve == "momentum":                # 甩一下后带惯性衰减
            p = 1 - (1 - k) ** 2.2
        else:
            p = k
        pos = dist * p
        out.append(pos - prev)
        prev = pos
    return out


def pause(dur):
    return [0.0] * max(1, int(round(dur / STEP)))


def sine(dur, amp, period):
    """来回摆动(鼠标晃动的近似): 位置是正弦, 逐帧取差分。"""
    n = max(1, int(round(dur / STEP)))
    out = []
    prev = 0.0
    for i in range(n):
        t = (i + 1) * STEP
        pos = amp * __import__("math").sin(2 * 3.141592653589793 * t / period)
        out.append(pos - prev)
        prev = pos
    return out


def circle(dur, radius, period):
    """画圈: x、y 都是正弦但相位差 90 度。逐轴看和晃动几乎一样。"""
    import math
    n = max(1, int(round(dur / STEP)))
    xs, ys = [], []
    px = py = 0.0
    for i in range(n):
        t = (i + 1) * STEP
        x = radius * math.sin(2 * math.pi * t / period)
        y = radius * math.cos(2 * math.pi * t / period)
        xs.append(x - px)
        ys.append(y - py)
        px, py = x, y
    return xs, ys


def make_detector(m, cfg):
    """兼容两种构造签名(旧版只有 min_run)。"""
    try:
        return m.AxisShake(cfg["min_run"], cfg["reversals"], cfg["window"])
    except TypeError:
        return m.AxisShake(cfg["min_run"])


def run_detectors(m, dxs, dys, sens="normal"):
    """按主循环的方式驱动状态机，返回 (是否触发, 折返数, 用了多少秒)。"""
    profiles = getattr(m, "SHAKE_PROFILES", None) or {
        "normal": {"min_run": m.SHAKE_MIN_RUN, "reversals": m.SHAKE_REVERSALS,
                   "window": m.SHAKE_WINDOW}}
    cfg = profiles[sens]
    d0 = make_detector(m, cfg)
    d1 = make_detector(m, cfg)
    t = 0.0
    for i in range(max(len(dxs), len(dys))):
        t = i * STEP
        dx = dxs[i] if i < len(dxs) else 0.0
        dy = dys[i] if i < len(dys) else 0.0
        r0 = d0.feed(t, dx)
        r1 = d1.feed(t, dy)
        if (r0 or r1) and (d0.hit() or d1.hit()) and m.shake_is_linear(d0, d1):
            return True, max(len(d0.revs), len(d1.revs)), t
    return False, max(len(d0.revs), len(d1.revs)), t


# ---------------------------------------------------------------- 用例
def cases():
    """(名字, dx 轨迹, dy 轨迹, 期望是否触发)"""
    out = []

    # 1. 鼠标快速晃动：连续, 无停顿
    out.append(("鼠标快速晃", sine(0.55, 70, 0.19), [], True))

    # 2. 触控板: 快滑四下(左右左右), 每次之间抬手指 0.18s
    tp_fast = (swipe(0.22, 420) + pause(0.18) + swipe(0.22, -420) + pause(0.18)
               + swipe(0.22, 420) + pause(0.18) + swipe(0.22, -420))
    out.append(("触控板 4 次快滑(带抬指)", tp_fast, [], True))

    # 3. 触控板: 幅度小一点, 停顿 0.25s
    tp_slow = (swipe(0.28, 260) + pause(0.25) + swipe(0.28, -260) + pause(0.25)
               + swipe(0.28, 260) + pause(0.25) + swipe(0.28, -260))
    out.append(("触控板 4 次慢滑(停顿 0.25s)", tp_slow, [], True))

    # 4. 只来回一趟(1 次折返) —— 不该触发
    out.append(("只来回一趟(1 折返)", swipe(0.15, 200) + swipe(0.15, -200), [], False))

    # 5. 拖窗口: 单向长距离
    out.append(("单向拖拽 600px", swipe(1.2, 600, "ease"), [], False))

    # 6. 慢速来回拖(像对齐某个东西): 幅度大但很慢
    slow_drag = (swipe(1.0, 300) + pause(0.05) + swipe(1.0, -300) + pause(0.05)
                 + swipe(1.0, 300) + pause(0.05) + swipe(1.0, -300))
    out.append(("慢速来回拖(1s 一趟)", slow_drag, [], False))

    # 7. 手抖: 极小幅度高频抖动
    out.append(("手抖 ±3px", sine(0.8, 3, 0.08), [], False))

    # 8. 画圈: 两轴同时摆动, 半圈就够骗过单轴判定
    cx, cy = circle(0.9, 120, 0.45)
    out.append(("画圈(半径 120)", cx, cy, False))

    # 9. 长停顿后单向移动: 不能因为历史折返残留而误触
    out.append(("滑一下 -> 停 2s -> 再滑一下",
                swipe(0.22, 400) + pause(2.0) + swipe(0.22, -400) + pause(0.2)
                + swipe(0.22, 400) + pause(0.2) + swipe(0.22, -400), [], False))
    return out


def main():
    m = load_app()
    m.setup_log(False)
    ok_all = True
    print("%-28s %-8s %-8s %-10s %s" % ("用例", "期望", "实际", "折返数", "耗时"))
    print("-" * 66)
    for name, dxs, dys, want in cases():
        got, revs, dur = run_detectors(m, dxs, dys)
        good = (got == want)
        ok_all = ok_all and good
        print("%-28s %-8s %-8s %-10s %.2fs %s"
              % (name, "触发" if want else "不触发", "触发" if got else "不触发",
                 revs, dur, "" if good else "  <== 不符合预期"))
    print("-" * 66)
    print("==== %s ====" % ("全部符合预期" if ok_all else "有不符合预期的用例"))
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
