# -*- coding: utf-8 -*-
"""
好友切换测试（严格按用户要求）：
每次寻找目标好友前，双击左侧导航栏头像下方第一个「微信」图标按钮，切回主界面，
然后 ChatWith 选中目标好友。仅此而已，不做任何其它窗口操作。
"""
import ctypes
import time
import traceback

import psutil, win32gui, win32process


def find_wechat_hwnd():
    pids = {p.info['pid'] for p in psutil.process_iter(['pid', 'name'])
            if p.info['name'] == 'Weixin.exe'}
    hits = []
    def cb(hwnd, _):
        if win32gui.GetClassName(hwnd) == 'Qt51514QWindowIcon':
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            if pid in pids:
                hits.append(hwnd)
    win32gui.EnumWindows(cb, None)
    for h in hits:
        if '微信' in win32gui.GetWindowText(h):
            return h
    return hits[0] if hits else None


def get_chat_name(wx):
    try:
        info = wx.ChatInfo() or {}
    except Exception as e:
        return f"<ChatInfo异常: {e}>"
    if isinstance(info, dict):
        return info.get("chat_name") or info.get("name") or info.get("who") or str(info)
    return str(info)


def main():
    from wxauto4 import WeChat

    hwnd = find_wechat_hwnd()
    print(f"[窗口] hwnd={hwnd}")

    # 把窗口恢复到屏幕内、正常尺寸（物理像素约 1300x1540，之前实测该尺寸下会话列表/搜索框可见）
    ctypes.windll.user32.ShowWindow(hwnd, 9)  # SW_RESTORE
    ctypes.windll.user32.SetWindowPos(hwnd, 0, 40, 40, 1300, 1540,
                                      0x0004 | 0x0010)  # SWP_NOZORDER | SWP_NOACTIVATE
    ctypes.windll.user32.SetForegroundWindow(hwnd)
    time.sleep(1.0)
    r = win32gui.GetWindowRect(hwnd)
    print(f"[窗口] 恢复后 rect={r} 尺寸={r[2]-r[0]}x{r[3]-r[1]}")

    wx = WeChat(ads=False, resize=False)
    print(f"[连接] 成功，当前聊天={get_chat_name(wx)!r}")

    # 确认导航栏「微信」图标按钮定位正确
    from wxauto4.uia import uiautomation as auto
    root = auto.ControlFromHandle(hwnd)
    btn = root.ButtonControl(searchDepth=0xFFFFFFFF, Name='微信')
    print(f"[定位] 「微信」按钮 是否存在={btn.Exists(3)}")
    if btn.Exists(0):
        print(f"        按钮 rect={btn.BoundingRectangle}")

    targets = ["热风", "叶心缘", "hzzy", "法兰茜丝卡"]
    results = []

    # 场景1：主界面（双击微信图标后）→ 打开好友
    print("\n=== 场景1：双击微信图标 → 打开好友 ===")
    btn.DoubleClick()
    time.sleep(0.8)
    a = targets[0]
    t0 = time.time()
    wx.ChatWith(a, exact=True)
    dt = time.time() - t0
    time.sleep(0.4)
    cur = get_chat_name(wx)
    ok = (cur == a)
    print(f"  打开 {a!r}: 耗时{dt:.1f}s 实际={cur!r} {'PASS' if ok else 'FAIL'}")
    results.append(("场景1 主界面→打开好友", a, cur, ok))

    # 场景2：好友A界面 → 双击微信图标 → 切换好友B
    print("\n=== 场景2：好友A界面 → 双击微信图标 → 切换好友B ===")
    prev = a
    for b in targets[1:] + [targets[0]]:
        btn.DoubleClick()
        time.sleep(0.8)
        t0 = time.time()
        wx.ChatWith(b, exact=True)
        dt = time.time() - t0
        time.sleep(0.4)
        cur = get_chat_name(wx)
        ok = (cur == b)
        print(f"  {prev!r}→{b!r}: 耗时{dt:.1f}s 实际={cur!r} {'PASS' if ok else 'FAIL'}")
        results.append((f"场景2 切换 {prev}→{b}", b, cur, ok))
        prev = b

    print("\n" + "=" * 60)
    n_pass = sum(1 for r in results if r[3])
    for sc, exp, act, passed in results:
        print(f"  [{'PASS' if passed else 'FAIL'}] {sc}: 期望={exp!r} 实际={act!r}")
    print(f"  通过 {n_pass}/{len(results)}")
    print("=" * 60)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
