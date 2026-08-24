# -*- coding: utf-8 -*-
"""验收测试：在「app 运行时环境」下验证（代理被禁用 + 原始代理已暂存）。
仅科普式有界验证：红楼梦只抓前3回，道德经走索引下钻。"""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wikisource_parser as wp

print("[环境] WORKBUDDY_ORIGINAL_HTTPS_PROXY =",
      os.environ.get("WORKBUDDY_ORIGINAL_HTTPS_PROXY"))
print("[环境] NO_PROXY =", os.environ.get("NO_PROXY"),
      " HTTPS_PROXY =", os.environ.get("HTTPS_PROXY"))

DL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp_accept")
os.makedirs(DL, exist_ok=True)

def hr(t): print("\n" + "=" * 60 + f"\n{t}\n" + "=" * 60)

# 红楼梦（有界：前3回，避免长循环卡死；验证代理下能真实抓到正文）
hr("红楼梦（前3回，模拟 app 环境）")
chapters = wp.find_chapters("紅樓夢")
orig = wp.find_chapters
wp.find_chapters = lambda t: chapters[:3]
t0 = time.time()
try:
    kind, paths = wp.resolve_book("紅樓夢", DL)
    for p in paths:
        print(f"  OK 写出 {os.path.basename(p)}  大小={os.path.getsize(p)}  耗时={time.time()-t0:.1f}s")
    print("  结论:", "通过" if os.path.getsize(paths[0]) > 1000 else "失败(空)")
finally:
    wp.find_chapters = orig

# 道德經（索引下钻，模拟 app 环境）
hr("道德經（索引下钻，模拟 app 环境）")
t0 = time.time()
try:
    kind, paths = wp.resolve_book("道德經", DL)
    for p in paths:
        print(f"  OK 写出 {os.path.basename(p)}  大小={os.path.getsize(p)}  耗时={time.time()-t0:.1f}s")
    print("  结论:", "通过" if os.path.getsize(paths[0]) > 1000 else "失败(空)")
except wp.BookNotFound as e:
    print(f"  失败 BookNotFound: {e}  耗时={time.time()-t0:.1f}s")

# 不存在书名
hr("不存在书名")
try:
    wp.resolve_book("不存在的公有领域书籍xyz123", DL)
    print("  失败：未抛异常")
except wp.BookNotFound as e:
    print(f"  OK 正确抛 BookNotFound: {e}")

print("\n验收完成。")
