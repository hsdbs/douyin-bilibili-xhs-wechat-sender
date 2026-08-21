# -*- coding: utf-8 -*-
"""
阶段2b：QT_ACCESSIBILITY=1 重启微信后的验证测试。
1) 原始 UIA 探测：微信主窗口控件树是否有内容
2) wxauto4 连接测试
只读操作，不发送任何消息。
"""
import sys, time, traceback
import win32gui, win32process
import psutil

def find_weixin_main_hwnd():
    """找到属于 Weixin.exe 的 Qt51514QWindowIcon 顶层窗口"""
    pids = {p.info['pid'] for p in psutil.process_iter(['pid', 'name'])
            if p.info['name'] == 'Weixin.exe'}
    hits = []
    def cb(hwnd, _):
        if win32gui.GetClassName(hwnd) == 'Qt51514QWindowIcon':
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            if pid in pids:
                hits.append((hwnd, win32gui.GetWindowText(hwnd)))
    win32gui.EnumWindows(cb, None)
    return hits

print("=" * 55)
print("[1] 查找微信主窗口...")
wins = find_weixin_main_hwnd()
print("    找到窗口:", wins)
if not wins:
    print("!! 未找到微信窗口，请确认微信已登录")
    sys.exit(1)

hwnd, title = wins[0]

# 还原窗口
import ctypes
ctypes.windll.user32.ShowWindow(hwnd, 9)
time.sleep(2)

print("[2] 原始 UIA 全子树控件统计...")
import comtypes.client
from comtypes.gen.UIAutomationClient import IUIAutomation, TreeScope_Subtree
auto = comtypes.client.CreateObject(
    '{ff48dba4-60ef-4201-aa87-54103eef594e}', interface=IUIAutomation)
root = auto.ElementFromHandle(hwnd)
CT = {'Pane': 50033, 'Text': 50020, 'List': 50008, 'Edit': 50004,
      'Button': 50000, 'ListItem': 50007, 'Document': 50030}
total = 0
for name, ct in CT.items():
    cond = auto.CreatePropertyCondition(30003, ct)
    items = root.FindAll(TreeScope_Subtree, cond)
    total += items.Length
    line = f"    {name}: {items.Length} 个"
    if items.Length:
        el = items.GetElement(0)
        line += f"  首个: name={el.CurrentName[:20]!r} aid={el.CurrentAutomationId[:30]!r}"
    print(line)
print(f"    UIA 控件总数: {total}")

if total <= 1:
    print("!! UIA 树仍为空 -> QT_ACCESSIBILITY 方案无效")
else:
    print("OK UIA 树有内容 -> 继续 wxauto4 连接测试")

print("[3] wxauto4 连接测试...")
try:
    from wxauto4 import WeChat
    wx = WeChat(ads=False)
    print("    连接成功!")
    try:
        print("    ChatInfo():", wx.ChatInfo())
    except Exception:
        traceback.print_exc()
except Exception:
    print("    连接失败:")
    traceback.print_exc()

print("=" * 55)
print("阶段2b 测试结束")
