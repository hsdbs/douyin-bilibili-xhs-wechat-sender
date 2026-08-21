# -*- coding: utf-8 -*-
"""
小红书图文 / 视频解析 + 下载模块

基于 XHS-Downloader（JoeanAmier/XHS-Downloader）。由于该库依赖较重（fastapi/textual/
httpx[http2] 等）且版本易与主程序 venv 冲突，采用「独立进程」方案：
  本模块（运行在主程序 venv）→ subprocess 调用 tools/xhs/.venv 下的 _worker.py
  → worker 导入 XHS 提取详情并下载，输出 JSON → 本模块解析结果。

依赖：tools/xhs/ 目录（含源码 + .venv，已在前期验证阶段部署）。
Cookie：可选。不配 cookie 也能下基础清晰度视频与图文；配 cookie 可解锁高清原片。
"""
import json
import logging
import os
import subprocess
import time

from core.config import get_config, VIDEO_DIR, BASE_DIR

# 静音 httpx 日志（本进程虽不直接下载，但保留干净）
logging.getLogger("httpx").setLevel(logging.CRITICAL)


def _cfg(key, default=None):
    try:
        return get_config().get("xhs", {}).get(key, default)
    except Exception:
        return default


def _download_dir():
    d = _cfg("download_dir") or ""
    if d:
        return d
    return VIDEO_DIR


def _timeout():
    try:
        return int(_cfg("timeout", 10))
    except Exception:
        return 10


def _max_retry():
    try:
        return int(_cfg("max_retry", 3))
    except Exception:
        return 3


def _cookie():
    return (_cfg("cookie") or "").strip()


def _xhs_root():
    """返回 XHS-Downloader 目录（含 source/ 与 .venv/）。配置优先 → 内置 tools/xhs。"""
    configured = _cfg("xhs_root") or ""
    if configured and os.path.isdir(os.path.join(configured, "source")):
        return configured
    cand = os.path.join(BASE_DIR, "tools", "xhs")
    if os.path.isdir(os.path.join(cand, "source")):
        return cand
    return configured or ""


def _worker_python():
    root = _xhs_root()
    exe = os.path.join(root, ".venv", "Scripts", "python.exe")
    return exe if os.path.isfile(exe) else ""


def _worker_py():
    root = _xhs_root()
    return os.path.join(root, "_worker.py")


def _subprocess_env():
    """构造子进程环境，强制 worker 输出 UTF-8（Windows 默认 GBK 会导致中文乱码）。"""
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    return env


def _run_worker(url, download_dir, timeout=None):
    """调用独立 worker，返回解析后的 dict。"""
    python = _worker_python()
    worker = _worker_py()
    if not python or not os.path.isfile(worker):
        raise RuntimeError("XHS-Downloader 环境缺失（tools/xhs/.venv 或 _worker.py 不存在）")

    cmd = [
        python, worker,
        "--url", url,
        "--dir", download_dir,
        "--cookie", _cookie(),
        "--timeout", str(timeout if timeout else _timeout()),
    ]
    kwargs = dict(capture_output=True, timeout=600, env=_subprocess_env())
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW

    r = subprocess.run(cmd, **kwargs)
    out = (r.stdout or b"").decode("utf-8", "replace")
    data = None
    for line in out.strip().splitlines():
        line = line.strip()
        if line.startswith("{"):
            try:
                data = json.loads(line)
                break
            except Exception:
                continue
    if data is None:
        err = (r.stderr or b"").decode("utf-8", "replace").strip()
        raise RuntimeError(f"小红书 worker 无有效输出（{err[:200] or '未知错误'}）")
    if not data.get("ok"):
        raise RuntimeError(data.get("error") or "小红书解析失败")
    return data


def resolve_xhs(url):
    """统一同步入口：解析小红书链接（视频或图文）并下载，返回 (kind, file_paths)。"""
    download_dir = _download_dir()
    os.makedirs(download_dir, exist_ok=True)
    max_retry = _max_retry()
    last_err = None
    for attempt in range(max_retry):
        try:
            data = _run_worker(url, download_dir)
            paths = data.get("paths") or []
            if not paths:
                raise RuntimeError("小红书下载结果为空")
            return data.get("kind") or "note", paths
        except Exception as e:
            last_err = e
            if attempt < max_retry - 1:
                logging.warning("小红书解析第 %d 次失败: %s", attempt + 1, e)
                time.sleep(2)
    raise last_err


def test_xhs():
    """测试小红书解析环境：worker 环境 + XHS-Downloader 是否可用。返回 (ok, detail)。"""
    root = _xhs_root()
    if not root or not os.path.isdir(os.path.join(root, "source")):
        return False, "未找到 XHS-Downloader 源码（tools/xhs 缺失，请恢复或指定路径）"
    python = _worker_python()
    if not python:
        return False, "未找到 tools/xhs/.venv（需先部署 XHS-Downloader 依赖环境）"
    try:
        cmd = [python, _worker_py(), "--selftest"]
        kwargs = dict(capture_output=True, timeout=60, env=_subprocess_env())
        if os.name == "nt":
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        r = subprocess.run(cmd, **kwargs)
        out = (r.stdout or b"").decode("utf-8", "replace").strip()
        data = json.loads(out) if out.startswith("{") else {}
        if data.get("ok"):
            tip = "已配置 Cookie" if _cookie() else "未配置 Cookie（视频仅基础清晰度）"
            return True, f"XHS-Downloader {data.get('version', '?')} 就绪，{tip}"
        return False, f"XHS-Downloader 自检失败: {data.get('error', out[:120])}"
    except Exception as e:
        return False, f"小红书环境测试异常: {str(e)[:160]}"


if __name__ == "__main__":
    import sys as _sys
    url = _sys.argv[1] if len(_sys.argv) > 1 else None
    if not url:
        print("用法: python xhs_parser.py <小红书链接>")
        _sys.exit(1)
    kind, paths = resolve_xhs(url)
    print("下载完成:", kind, paths)
