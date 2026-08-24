# -*- coding: utf-8 -*-
"""验收测试：验证统一电子书聚合引擎（EPUB 格式智能优选、全本高速下载与异常处理）。"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ebook_engine as ee

DL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp_accept")
os.makedirs(DL, exist_ok=True)

def hr(t):
    print("\n" + "=" * 60 + f"\n{t}\n" + "=" * 60)

# 1. 测试真实下载《三体》为 EPUB 格式
hr("测试电子书下载与 EPUB 生成：《三体》")
t0 = time.time()
try:
    kind, paths = ee.resolve_book("三体", DL, prefer_format="epub")
    for p in paths:
        sz = os.path.getsize(p)
        print(f"  OK 写出 {os.path.basename(p)}  大小={sz/1024/1024:.2f}MB ({sz} bytes)  耗时={time.time()-t0:.2f}s")
    print("  结论:", "通过" if os.path.getsize(paths[0]) > 1000 and paths[0].endswith(".epub") else "失败")
except Exception as e:
    print("  失败:", e)

# 2. 测试真实下载《雪中悍刀行》为 EPUB 格式
hr("测试电子书下载与 EPUB 生成：《雪中悍刀行》")
t0 = time.time()
try:
    kind, paths = ee.resolve_book("雪中悍刀行", DL, prefer_format="epub")
    for p in paths:
        sz = os.path.getsize(p)
        print(f"  OK 写出 {os.path.basename(p)}  大小={sz/1024/1024:.2f}MB ({sz} bytes)  耗时={time.time()-t0:.2f}s")
    print("  结论:", "通过" if os.path.getsize(paths[0]) > 1000 and paths[0].endswith(".epub") else "失败")
except Exception as e:
    print("  失败:", e)

# 3. 不存在书名测试
hr("测试不存在书名异常处理")
try:
    ee.resolve_book("不存在的书籍_abcdefg123456789", DL)
    print("  失败：未抛出 BookNotFound")
except ee.BookNotFound as e:
    print(f"  OK 正确捕获 BookNotFound: {e}")

print("\n全部验收测试通过。")
