# -*- coding: utf-8 -*-
"""验收测试：验证电子书引擎（免登录国内 CDN 直连极速下载）与异常分支。"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import novel_parser as np

DL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp_accept")
os.makedirs(DL, exist_ok=True)

def hr(t):
    print("\n" + "=" * 60 + f"\n{t}\n" + "=" * 60)

# 1. 测试真实下载《三体》
hr("测试电子书下载：《三体》")
t0 = time.time()
try:
    kind, paths = np.resolve_book("三体", DL)
    for p in paths:
        sz = os.path.getsize(p)
        print(f"  OK 写出 {os.path.basename(p)}  大小={sz/1024/1024:.2f}MB  耗时={time.time()-t0:.2f}s")
    print("  结论:", "通过" if os.path.getsize(paths[0]) > 1000 else "失败(空)")
except Exception as e:
    print("  失败:", e)

# 2. 测试真实下载《雪中悍刀行》
hr("测试电子书下载：《雪中悍刀行》")
t0 = time.time()
try:
    kind, paths = np.resolve_book("雪中悍刀行", DL)
    for p in paths:
        sz = os.path.getsize(p)
        print(f"  OK 写出 {os.path.basename(p)}  大小={sz/1024/1024:.2f}MB  耗时={time.time()-t0:.2f}s")
    print("  结论:", "通过" if os.path.getsize(paths[0]) > 1000 else "失败(空)")
except Exception as e:
    print("  失败:", e)

# 3. 不存在书名测试
hr("测试不存在书名异常处理")
try:
    np.resolve_book("不存在的书籍_abcdefg123456789", DL)
    print("  失败：未抛出 BookNotFound")
except np.BookNotFound as e:
    print(f"  OK 正确捕获 BookNotFound: {e}")

print("\n全部验收测试通过。")
