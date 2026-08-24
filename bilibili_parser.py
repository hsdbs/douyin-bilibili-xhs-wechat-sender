# -*- coding: utf-8 -*-
"""
Bilibili 视频解析与下载模块（基于 yutto CLI / Python API）。

说明：
  - 依赖 yutto（已加入 requirements.txt，安装后提供 yutto 命令行）。
  - B站无登录态默认只能下载 360P/480P，若需高清可在配置中填入 SESSDATA。
  - yutto 自动调用 ffmpeg 合并音视频流（已在 tools/ffmpeg 提供兜底）。
"""
import glob
import os
import shutil
import subprocess
import sys
import tempfile

from core.config import get_config
from core.logger import logger


def _cfg(key, default=None):
    b = get_config().get("bilibili", {})
    return b.get(key, default)


def _timeout():
    return int(_cfg("timeout", 180))


def _auth():
    """读取用户配置的 SESSDATA（纯字符串或 SESSDATA=xxx 均可）。"""
    sess = (_cfg("sessdata") or "").strip()
    if sess:
        if sess.startswith("SESSDATA="):
            return sess
        return f"SESSDATA={sess}"
    return (_cfg("auth") or "").strip()


def _yutto_bin():
    """探测 yutto 可执行文件路径。配置优先 → PATH → 常见安装位置。"""
    configured = _cfg("yutto_path") or ""
    if configured and os.path.exists(configured):
        return configured

    which = shutil.which("yutto")
    if which:
        return which

    # Windows 常见 Python Scripts 目录
    candidates = [
        os.path.join(sys.prefix, "Scripts", "yutto.exe"),
        os.path.join(sys.prefix, "bin", "yutto"),
        os.path.expanduser(r"~\AppData\Local\Programs\Python\Python312\Scripts\yutto.exe"),
        os.path.expanduser(r"~\AppData\Local\Programs\Python\Python311\Scripts\yutto.exe"),
        os.path.expanduser(r"~\AppData\Local\Programs\Python\Python310\Scripts\yutto.exe"),
        os.path.expanduser(r"~\AppData\Roaming\Python\Python312\Scripts\yutto.exe"),
        r"E:\py\Scripts\yutto.exe",
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    return None


def _ffmpeg_dir():
    """探测 ffmpeg 所在目录，以便将其加到子进程 PATH。"""
    which = shutil.which("ffmpeg")
    if which:
        return os.path.dirname(os.path.abspath(which))
    bundled = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tools", "ffmpeg")
    if os.path.exists(os.path.join(bundled, "ffmpeg.exe")) or os.path.exists(os.path.join(bundled, "ffmpeg")):
        return bundled
    return None


def _clean_dir(d):
    try:
        shutil.rmtree(d, ignore_errors=True)
    except Exception:
        pass


def _find_media(directory):
    """在目录下递归搜索生成的视频文件（mp4/mkv/flv 等），按修改时间倒序。"""
    exts = ("*.mp4", "*.mkv", "*.flv", "*.mov", "*.webm")
    found = []
    for ext in exts:
        found.extend(glob.glob(os.path.join(directory, "**", ext), recursive=True))
    found = [p for p in found if os.path.isfile(p) and os.path.getsize(p) > 1024]
    found.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    return found


def _run_yutto(url, tmpdir):
    """调用 yutto CLI 下载单个视频。返回最终视频绝对路径或抛异常。"""
    bin_path = _yutto_bin()
    if not bin_path:
        raise RuntimeError("未找到 yutto。请执行 pip install yutto，或在配置中指定 yutto_path。")

    cmd = [
        bin_path,
        url,
        "-d", tmpdir,
        "--no-danmaku",
        "--no-subtitle",
        "--no-color",
    ]

    auth = _auth()
    if auth:
        cmd += ["--auth", auth]

    kwargs = dict(
        capture_output=True,
        timeout=_timeout(),
    )
    # Windows 隐藏命令行黑框
    if sys.platform == "win32":
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        kwargs["startupinfo"] = si

    # 注入 ffmpeg 路径到子进程 PATH
    env = os.environ.copy()
    ff = _ffmpeg_dir()
    if ff:
        env["PATH"] = ff + os.pathsep + env.get("PATH", "")
    kwargs["env"] = env

    logger.info(f"[B站] 执行 yutto 下载: {url}")
    try:
        proc = subprocess.run(cmd, **kwargs)
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"B站视频下载超时（超过 {_timeout()} 秒）")
    except Exception as e:
        raise RuntimeError(f"调用 yutto 失败: {e}")

    stdout = (proc.stdout or b"").decode("utf-8", errors="ignore")
    stderr = (proc.stderr or b"").decode("utf-8", errors="ignore")

    if proc.returncode != 0:
        msg = (stderr or stdout).strip()
        logger.error(f"[B站] yutto 失败 (code={proc.returncode}):\n{msg}")
        raise RuntimeError(f"B站下载失败: {msg[-300:] if msg else '未知错误'}")

    medias = _find_media(tmpdir)
    if not medias:
        logger.error(f"[B站] yutto 执行成功但未找到产出视频。输出：\n{stdout}\n{stderr}")
        raise RuntimeError("B站解析完成但未生成视频文件")

    return medias[0]


def resolve_bilibili(url):
    """
    对外主入口：解析并下载 B站 视频。
    返回: ("video", [video_file_path])
    异常: RuntimeError（带用户可读原因）
    """
    cfg = get_config()
    b_cfg = cfg.get("bilibili", {})
    if not b_cfg.get("enabled", True):
        raise RuntimeError("B站解析功能已被用户禁用")

    dl_dir = b_cfg.get("download_dir") or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "videos"
    )
    os.makedirs(dl_dir, exist_ok=True)

    tmpdir = tempfile.mkdtemp(prefix="bili_", dir=dl_dir)
    try:
        tmp_video = _run_yutto(url, tmpdir)
        filename = os.path.basename(tmp_video)
        final_path = os.path.join(dl_dir, filename)

        # 若同名文件存在则覆盖，避免移动失败
        if os.path.exists(final_path):
            try:
                os.remove(final_path)
            except Exception:
                pass
        shutil.move(tmp_video, final_path)
        logger.info(f"[B站] 视频已就绪: {final_path} ({os.path.getsize(final_path)} bytes)")
        return "video", [final_path]
    finally:
        _clean_dir(tmpdir)


def test_bilibili():
    """环境自检：yutto 与 ffmpeg 是否就绪。返回 (ok, detail_message)。"""
    bin_path = _yutto_bin()
    if not bin_path:
        return False, "未找到 yutto（请在 Python 环境中执行 pip install yutto）"
    ff = _ffmpeg_dir()
    ff_ok = bool(ff)

    # 尝试读取 yutto 版本
    try:
        proc = subprocess.run([bin_path, "--version"], capture_output=True, timeout=5)
        ver = proc.stdout.decode("utf-8", errors="ignore").strip() or "已就绪"
    except Exception as e:
        ver = f"探测异常: {e}"

    if not ff_ok:
        return False, f"找到 yutto ({ver})，但未找到 FFmpeg（视频合并将失败）"
    return True, f"yutto 可用（{ver}），FFmpeg 已就绪"
