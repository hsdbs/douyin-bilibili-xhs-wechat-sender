# -*- coding: utf-8 -*-
"""
阶段2最小测试：仅连接微信并读取基本信息。
只读操作，不发送任何消息。
"""
import sys
import traceback

print("=" * 50)
print("[1] Python 版本:", sys.version.replace("\n", " "))

try:
    import wxauto4
    print("[2] wxauto4 版本:", getattr(wxauto4, "__version__", "未知"))
except Exception:
    print("[2] wxauto4 导入失败:")
    traceback.print_exc()
    sys.exit(1)

try:
    from wxauto4 import WeChat
    wx = WeChat()
    print("[3] 连接微信: 成功")
except Exception:
    print("[3] 连接微信: 失败")
    traceback.print_exc()
    sys.exit(1)

# 读取当前聊天窗口信息（只读）
try:
    info = wx.ChatInfo()
    print("[4] 当前聊天窗口信息 ChatInfo():", info)
except Exception:
    print("[4] ChatInfo() 读取失败:")
    traceback.print_exc()

# 尝试读取当前登录账号（不同版本方法名可能不同，逐个尝试）
for attr in ("GetCurrentUser", "GetSelfInfo", "A_MyInfo", "CurrentUser"):
    fn = getattr(wx, attr, None)
    if callable(fn):
        try:
            print(f"[5] {attr}():", fn())
            break
        except Exception:
            print(f"[5] {attr}() 调用失败:")
            traceback.print_exc()
else:
    print("[5] 未找到可用的账号信息方法（不影响连接结论）")

print("=" * 50)
print("阶段2测试结束")
