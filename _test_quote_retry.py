# -*- coding: utf-8 -*-
"""重新测试「引用 + 发文件」：分两个独立测试，都用新鲜消息对象。"""
import os
import time

from wxauto4 import WeChat
import main as biz

TEST_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "发送测试_请忽略.txt")

biz._maximize_wechat()
wx = WeChat(ads=False, resize=False)
ok = biz.switch_chat(wx, "文件传输助手")
print("切换会话:", ok)


def find_text_msg():
    """每次重新取一条新鲜的文本消息对象。"""
    for mm in wx.GetAllMessage():
        if getattr(mm, "type", None) in ("text", "other") and getattr(mm, "content", ""):
            return mm
    return None


def show_new(before, tag):
    time.sleep(1.5)
    after = wx.GetAllMessage()
    new = [m for m in after if getattr(m, "content", "") not in before]
    print(f"\n[{tag}] 新增 {len(new)} 条:")
    for m in new:
        print(f"  type={getattr(m,'type',None)!r} sender={getattr(m,'sender',None)!r} "
              f"content={getattr(m,'content','')!r}")
    return [getattr(m, "content", "") for m in after]


before = [getattr(m, "content", "") for m in wx.GetAllMessage()]

# ===== 测试 1：手动引用 + 发文字（验证引用块是否真的出现）=====
print("\n===== 测试 1：select_option('引用') + SendMsg(文字) =====")
t1 = find_text_msg()
print("引用目标:", repr((getattr(t1, "content", "") or "")[:40]))
try:
    t1.right_click()
    time.sleep(0.5)
    r = t1.select_option("引用")
    print("select_option 返回:", r.to_dict() if hasattr(r, "to_dict") else r)
    time.sleep(0.5)
    r2 = wx.SendMsg("引用验证文字1", who="文件传输助手")
    print("SendMsg 返回:", r2.to_dict() if hasattr(r2, "to_dict") else r2)
except Exception as e:
    print("测试1 异常:", type(e).__name__, str(e)[:200])
before = show_new(before, "测试1")

# ===== 测试 2：手动引用 + 发文件（看文件是否带引用）=====
print("\n===== 测试 2：select_option('引用') + SendFiles(文件) =====")
t2 = find_text_msg()
print("引用目标:", repr((getattr(t2, "content", "") or "")[:40]))
try:
    t2.right_click()
    time.sleep(0.5)
    r = t2.select_option("引用")
    print("select_option 返回:", r.to_dict() if hasattr(r, "to_dict") else r)
    time.sleep(0.5)
    r2 = wx.SendFiles(TEST_FILE, who="文件传输助手")
    print("SendFiles 返回:", r2.to_dict() if hasattr(r2, "to_dict") else r2)
except Exception as e:
    print("测试2 异常:", type(e).__name__, str(e)[:200])
before = show_new(before, "测试2")

biz._minimize_wechat()
print("\n完成")
