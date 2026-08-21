# -*- coding: utf-8 -*-
"""精简测试：引用 + 发一个全新文件，确认文件消息 type 是否带引用。"""
import os
import time

from wxauto4 import WeChat
import main as biz

# 生成一个全新文件，避免 content 与历史消息重复
TMP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "引用测试_请忽略.txt")
with open(TMP, "w", encoding="utf-8") as f:
    f.write("引用测试 " + time.strftime("%H%M%S"))
print("临时文件:", TMP)

biz._maximize_wechat()
wx = WeChat(ads=False, resize=False)
ok = biz.switch_chat(wx, "文件传输助手")
print("切换会话:", ok)

# 快照：记录发送前的消息条数 + content
before_contents = [getattr(m, "content", "") for m in wx.GetAllMessage()]
before_count = len(before_contents)

# 找一条新鲜文本消息
target = None
for mm in wx.GetAllMessage():
    if getattr(mm, "type", None) in ("text", "other") and getattr(mm, "content", ""):
        target = mm
        break
print("引用目标:", repr((getattr(target, "content", "") or "")[:40]))

# 引用 + 发文件
target.right_click()
time.sleep(0.5)
r = target.select_option("引用")
print("select_option('引用') =>", r.to_dict() if hasattr(r, "to_dict") else r)
time.sleep(0.5)
r2 = wx.SendFiles(TMP, who="文件传输助手")
print("SendFiles =>", r2.to_dict() if hasattr(r2, "to_dict") else r2)

# 等待后读取，按「文件名」定位这条新文件消息
time.sleep(2.5)
after = wx.GetAllMessage()
print(f"\n发送前 {before_count} 条，发送后 {len(after)} 条")
print("最新 5 条消息:")
for m in after[-5:]:
    t = getattr(m, "type", None)
    c = (getattr(m, "content", "") or "")
    s = getattr(m, "sender", None)
    print(f"  type={t!r}  sender={s!r}  content={c!r}")

# 清理临时文件
try:
    os.remove(TMP)
except Exception:
    pass

biz._minimize_wechat()
print("\n完成")
