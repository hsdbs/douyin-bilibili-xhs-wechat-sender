# -*- coding: utf-8 -*-
"""
小红书作品提取/下载独立 worker（在 tools/xhs/.venv 下运行）。

为何独立进程：XHS-Downloader 依赖较重的 fastapi/textual/httpx[http2] 等，
且版本与主程序 venv 可能冲突，故放在 tools/xhs/.venv 单独运行，由 xhs_parser.py
通过 subprocess 调用。主程序只解析本脚本输出的 JSON。

输出约定：stdout 只输出一行 JSON（XHS 内部日志重定向到 stderr）。
  成功: {"ok": true, "kind": "video"|"note", "paths": ["..."]}
  失败: {"ok": false, "error": "..."}

用法：
  python _worker.py --url <链接> --dir <下载目录> [--cookie <cookie>] [--timeout 10]
  python _worker.py --selftest      # 输出 {"ok": true, "version": "2.8"}
"""
import argparse
import asyncio
import json
import os
import shutil
import sys
import tempfile

import httpx

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36")

_VIDEO_KINDS = {"视频"}
_NOTE_KINDS = {"图文", "图集"}


def _sanitize(name):
    for ch in '\\/:*?"<>|':
        name = name.replace(ch, "_")
    return name.strip() or "xhs"


def _https(addr):
    if not addr:
        return ""
    addr = addr.strip()
    if addr.startswith("http://"):
        addr = "https://" + addr[len("http://"):]
    return addr


async def _download(urls, kind, title, author, outdir):
    """下载视频或图文文件到 outdir，返回本地路径列表。"""
    headers = {"User-Agent": UA, "Referer": "https://www.xiaohongshu.com/"}
    paths = []
    async with httpx.AsyncClient(headers=headers, follow_redirects=True, timeout=120) as c:
        if kind in _NOTE_KINDS:
            base = _sanitize(f"{title[:40]}_{author}")
            for i, addr in enumerate(urls):
                addr = _https(addr)
                if not addr:
                    continue
                try:
                    r = await c.get(addr)
                    if r.status_code == 200 and len(r.content) > 1000:
                        path = os.path.join(outdir, f"{base}_{i + 1}.jpg")
                        with open(path, "wb") as f:
                            f.write(r.content)
                        paths.append(path)
                except Exception:
                    continue
        else:  # 视频
            filename = f"{_sanitize(title)[:40]}_{_sanitize(author)}.mp4"
            for addr in urls:
                addr = _https(addr)
                if not addr:
                    continue
                try:
                    r = await c.get(addr)
                    if r.status_code == 200 and len(r.content) > 1000:
                        path = os.path.join(outdir, filename)
                        with open(path, "wb") as f:
                            f.write(r.content)
                        paths.append(path)
                        break
                except Exception:
                    continue
    return paths


async def work(args):
    from source.application import XHS  # noqa: E402  延迟导入

    # 提速：XHS-Downloader 默认每次请求后随机 sleep 平均 6 秒（对数正态，反爬限速）。
    # 单条链接只需 2 次请求（短链重定向 + 详情），6s×2 ≈ 12s 是主要延迟来源。
    # 这里把 request 模块的 sleep_time 换成固定约 1 秒，仍保留一定间隔防风控。
    import source.application.request as _req

    async def _fast_sleep():
        await asyncio.sleep(1.0)

    _req.sleep_time = _fast_sleep

    work_path = tempfile.mkdtemp(prefix="xhs_")
    # 把 XHS 内部日志重定向到 stderr，保证 stdout 只留给最终 JSON
    real_stdout = sys.stdout
    sys.stdout = sys.stderr
    try:
        async with XHS(
            work_path=work_path,
            folder_name="xhs",
            cookie=args.cookie or "",
            timeout=args.timeout,
            record_data=False,
            download_record=False,
            note_format="",
            image_format="jpeg",
            author_archive=False,
            write_mtime=False,
        ) as xhs:
            result = await xhs.extract(args.url, download=False)
    finally:
        sys.stdout = real_stdout
        shutil.rmtree(work_path, ignore_errors=True)

    if not result:
        return {"ok": False, "error": "未获取到作品信息（链接失效或需登录）"}
    d = result[0] if isinstance(result, list) else result
    if not isinstance(d, dict) or not d:
        return {"ok": False, "error": "作品详情为空"}

    kind = (d.get("作品类型") or "").strip()
    title = (d.get("作品标题") or "").strip()
    author = (d.get("作者昵称") or "unknown")
    addrs = d.get("下载地址") or []

    if kind not in _VIDEO_KINDS and kind not in _NOTE_KINDS:
        return {"ok": False, "error": f"不支持的作品类型：{kind or '未知'}"}
    if not addrs:
        return {"ok": False, "error": "未获取到下载地址"}

    os.makedirs(args.dir, exist_ok=True)
    paths = await _download(addrs, kind, title, author, args.dir)
    if not paths:
        return {"ok": False, "error": "下载失败：所有地址均不可用"}
    return {"ok": True, "kind": "video" if kind in _VIDEO_KINDS else "note", "paths": paths}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--url", default="")
    p.add_argument("--dir", default="")
    p.add_argument("--cookie", default="")
    p.add_argument("--timeout", type=int, default=10)
    p.add_argument("--selftest", action="store_true")
    args = p.parse_args()

    if args.selftest:
        try:
            from source.application import XHS
            print(json.dumps({
                "ok": True,
                "version": (f"{getattr(XHS, 'VERSION_MAJOR', '?')}."
                            f"{getattr(XHS, 'VERSION_MINOR', '?')}"),
            }, ensure_ascii=True))
        except Exception as e:
            print(json.dumps({"ok": False, "error": str(e)}, ensure_ascii=True))
        return

    if not args.url or not args.dir:
        print(json.dumps({"ok": False, "error": "缺少 --url 或 --dir 参数"}, ensure_ascii=True))
        return

    try:
        result = asyncio.run(work(args))
    except Exception as e:
        result = {"ok": False, "error": str(e)}
    print(json.dumps(result, ensure_ascii=True))


if __name__ == "__main__":
    main()
