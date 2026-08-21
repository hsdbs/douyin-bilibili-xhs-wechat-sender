# -*- coding: utf-8 -*-
"""
ChatWith 切换好友 重测 v2 —— 验证「窗口太小导致其它会话项被屏蔽」的根因。

关键修正：
  1. 连接前把微信主窗口 恢复 + 最大化，保证会话列表/搜索框完整显示。
  2. WeChat(resize=False) —— 阻止 wxauto4 自动重设窗口尺寸（避免把窗缩回去）。

测试场景：
  场景1 —— 主界面时直接打开某位好友
  场景2 —— 已在好友聊天界面时切换到另一位好友
只切换 + ChatInfo 校验，不发消息。
"""
import sys
import time
import ctypes
import traceback


def find_wechat_hwnd():
    import psutil, win32gui, win32process
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


def get_window_size(hwnd):
    import win32gui
    r = win32gui.GetWindowRect(hwnd)
    return (r[2] - r[0], r[3] - r[1]), win32gui.GetWindowPlacement(hwnd)[1]


def get_chat_name(wx):
    try:
        info = wx.ChatInfo() or {}
    except Exception as e:
        return None, f"<ChatInfo异常: {e}>"
    if isinstance(info, dict):
        name = info.get("chat_name") or info.get("name") or info.get("who")
    else:
        name = str(info)
    return name, info


def main():
    from wxauto4 import WeChat

    hwnd = find_wechat_hwnd()
    print(f"[窗口] 主窗口 hwnd={hwnd}")
    if hwnd:
        # 恢复 + 最大化
        ctypes.windll.user32.ShowWindow(hwnd, 9)      # SW_RESTORE
        ctypes.windll.user32.SetForegroundWindow(hwnd)
        time.sleep(0.5)
        ctypes.windll.user32.ShowWindow(hwnd, 3)      # SW_MAXIMIZE
        time.sleep(0.8)
        size, cmd = get_window_size(hwnd)
        print(f"[窗口] 最大化后尺寸={size} showCmd={cmd}")

    print("[连接] 正在连接微信 (resize=False) ...")
    wx = WeChat(ads=False, resize=False)
    print("[连接] 成功")

    if hwnd:
        size, cmd = get_window_size(hwnd)
        print(f"[窗口] 连接后尺寸={size} showCmd={cmd}")

    cur, raw = get_chat_name(wx)
    print(f"[基线] 当前聊天: {cur!r} (ChatInfo={raw!r})")

    try:
        sessions = wx.GetSession()
        names = [getattr(s, "name", s) for s in sessions]
        print(f"[会话] 可见 {len(sessions)} 个: {names}")
    except Exception as e:
        names = []
        print(f"[会话] GetSession 异常: {e}")

    targets = ["热风", "叶心缘", "hzzy", "法兰茜丝卡"]
    print(f"[目标] {targets}")
    results = []

    # 场景1
    print("\n" + "#" * 60)
    print("# 场景1：主界面 → 直接打开某位好友")
    print("#" * 60)
    try:
        wx.SwitchToChat()
        time.sleep(0.8)
    except Exception as e:
        print(f"[场景1] SwitchToChat 异常(忽略): {e}")

    a = targets[0]
    t0 = time.time()
    try:
        wx.ChatWith(a, exact=True)
        ok, note = True, "无异常"
    except Exception as e:
        ok, note = False, f"异常: {e}"
    dt = time.time() - t0
    time.sleep(0.4)
    cur2, _ = get_chat_name(wx)
    passed = ok and cur2 == a
    print(f"[场景1] 打开 {a!r}: {dt:.1f}s | 期望={a!r} 实际={cur2!r} | {'PASS' if passed else 'FAIL'} ({note})")
    results.append(("场景1 主界面→打开好友", a, cur2, passed, note))

    # 场景2
    print("\n" + "#" * 60)
    print("# 场景2：已在好友聊天界面 → 切换到另一位好友")
    print("#" * 60)
    prev = a
    for b in targets[1:] + [targets[0]]:
        t0 = time.time()
        try:
            wx.ChatWith(b, exact=True)
            ok, note = True, "无异常"
        except Exception as e:
            ok, note = False, f"异常: {e}"
        dt = time.time() - t0
        time.sleep(0.4)
        cur2, _ = get_chat_name(wx)
        passed = ok and cur2 == b
        print(f"[场景2] {prev!r} → {b!r}: {dt:.1f}s | 期望={b!r} 实际={cur2!r} | {'PASS' if passed else 'FAIL'} ({note})")
        results.append((f"场景2 切换 {prev}→{b}", b, cur2, passed, note))
        prev = b

    # 汇总
    print("\n" + "=" * 60)
    n_pass = sum(1 for r in results if r[3])
    for sc, exp, act, passed, note in results:
        print(f"  [{'PASS' if passed else 'FAIL'}] {sc}: 期望={exp!r} 实际={act!r} {note}")
    print(f"  通过 {n_pass}/{len(results)}")
    print("=" * 60)
    print("测试结束")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        print("脚本异常退出:")
        traceback.print_exc()
        sys.exit(1)
