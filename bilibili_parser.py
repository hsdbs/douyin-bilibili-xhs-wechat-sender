# -*- coding: utf-8 -*-
"""
B站视频解析 + 下载模块

基于 yutto（yutto-dev/yutto，CLI 工具）子进程调用：
  分享链接 → subprocess 调用 `yutto <url>` → 下载并 FFmpeg 混流为 mp4。

依赖：
  - yutto（建议 `uv tool install yutto`，或 pip 安装后保证 `yutto` 在 PATH）
  - FFmpeg（yutto 混流必需；项目已内置 tools/ffmpeg/ffmpeg.exe，可自动探测）

配置（config/config.json 的 bilibili 段）：
  - yutto_path / ffmpeg_path：可执行文件路径，留空自动探测
  - quality：清晰度（16=360P 32=480P 64=720P 80=1080P，默认 64）
  - auth：B站 SESSDATA cookie（可选，高清/大会员需；留空游客态）
  - download_dir：下载目录（默认与抖音共用 videos/）
  - timeout：下载超时秒数

注意：yutto 是纯 CLI，本模块通过 subprocess 调用，下载到临时目录后把 mp4 移入正式目录。
"""
import glob
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import time

from core.config import get_config, VIDEO_DIR, BASE_DIR

# 静音 yutto 底层日志（如 httpx 噪音，虽然子进程独立，这里主要保证本进程干净）
logging.getLogger("httpx").setLevel(logging.CRITICAL)

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36")


def _cfg(key, default=None):
    try:
        return get_config().get("bilibili", {}).get(key, default)
    except Exception:
        return default


def _download_dir():
    d = _cfg("download_dir") or ""
    if d:
        return d
    return VIDEO_DIR


def _quality():
    try:
        return int(_cfg("quality", 64))
    except Exception:
        return 64


def _timeout():
    try:
        return int(_cfg("timeout", 600))
    except Exception:
        return 600


def _max_retry():
    try:
        return int(_cfg("max_retry", 2))
    except Exception:
        return 2


def _auth():
    return (_cfg("auth") or "").strip()


def _yutto_bin():
    """探测 yutto 可执行文件路径。配置优先 → PATH → 常见安装位置。"""
    configured = _cfg("yutto_path") or ""
    if configured and os.path.isfile(configured):
        return configured
    p = shutil.which("yutto")
    if p:
        return p
    home = os.path.expanduser("~")
    for cand in (
        os.path.join(home, ".local", "bin", "yutto.exe"),
        os.path.join(home, ".local", "bin", "yutto"),
    ):
        if os.path.isfile(cand):
            return cand
    return "yutto"  # 回退：寄希望于 PATH 上有


def _ffmpeg_bin():
    """探测 FFmpeg 可执行文件路径。配置优先 → PATH → 项目内置 tools/ffmpeg。"""
    configured = _cfg("ffmpeg_path") or ""
    if configured and os.path.isfile(configured):
        return configured
    p = shutil.which("ffmpeg")
    if p:
        return p
    cand = os.path.join(BASE_DIR, "tools", "ffmpeg", "ffmpeg.exe")
    if os.path.isfile(cand):
        return cand
    return None


def _build_env():
    """构造子进程环境变量，把 FFmpeg 所在目录加进 PATH，并强制 UTF-8 输出。"""
    env = os.environ.copy()
    ffmpeg = _ffmpeg_bin()
    if ffmpeg:
        d = os.path.dirname(ffmpeg)
        env["PATH"] = d + os.pathsep + env.get("PATH", "")
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    return env


def _run_yutto(url, tmpdir):
    """调用 yutto 下载到 tmpdir，返回 (returncode, stdout, stderr)。"""
    cmd = [
        _yutto_bin(),
        url,
        "-d", tmpdir,
        "-q", str(_quality()),
        "--no-danmaku",
        "--no-subtitle",
        "--no-cover",
        "--output-format", "mp4",
        "--no-progress",
        "--no-color",
    ]
    auth = _auth()
    if auth:
        cmd += ["--auth", auth]

    kwargs = dict(
        capture_output=True,
        timeout=_timeout(),
        env=_build_env(),
    )
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW

    logging.info("执行 yutto: %s", " ".join(cmd[:4]) + " ...")
    r = subprocess.run(cmd, **kwargs)
    stdout = (r.stdout or b"").decode("utf-8", "replace")
    stderr = (r.stderr or b"").decode("utf-8", "replace")
    return r.returncode, stdout, stderr


def _find_mp4(tmpdir):
    """在临时目录里找 yutto 产出的 mp4 文件，返回第一个匹配的完整路径或 None。"""
    for p in sorted(glob.glob(os.path.join(tmpdir, "*.mp4"))):
        if os.path.isfile(p) and os.path.getsize(p) > 1000:
            return p
    return None


def _sanitize(name):
    for ch in '\\/:*?"<>|':
        name = name.replace(ch, "_")
    name = name.strip()
    return name or "bilibili"


def resolve_bilibili(url):
    """统一同步入口：解析 B站视频链接并下载，返回 ("video", [mp4_path])。"""
    download_dir = _download_dir()
    os.makedirs(download_dir, exist_ok=True)
    max_retry = _max_retry()
    last_err = None

    for attempt in range(max_retry):
        tmpdir = tempfile.mkdtemp(prefix="bili_")
        try:
            code, stdout, stderr = _run_yutto(url, tmpdir)
            mp4 = _find_mp4(tmpdir)
            if not mp4:
                tail = (stderr or stdout).strip().splitlines()
                detail = tail[-1][:200] if tail else f"exit code {code}"
                raise RuntimeError(f"yutto 下载失败（未产出 mp4）：{detail}")

            # 移入正式目录（沿用 yutto 的标题文件名，过长则截断）
            name = os.path.basename(mp4)
            if len(name) > 120:
                name = name[:90] + os.path.splitext(name)[1]
            dest = os.path.join(download_dir, name)
            # 目标已存在则换名
            if os.path.exists(dest):
                stem, ext = os.path.splitext(name)
                dest = os.path.join(download_dir, f"{stem}_{int(time.time())}{ext}")
            shutil.move(mp4, dest)
            logging.info("B站视频下载完成: %s", dest)
            return "video", [dest]
        except Exception as e:
            last_err = e
            if attempt < max_retry - 1:
                logging.warning("B站解析第 %d 次失败: %s", attempt + 1, e)
                time.sleep(2)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    raise last_err


def test_bilibili():
    """测试 B站解析环境：yutto / FFmpeg 是否可用。返回 (ok, detail)。"""
    yutto = _yutto_bin()
    if yutto == "yutto" and not shutil.which("yutto"):
        return False, "未找到 yutto 可执行文件（请安装 yutto 或在配置里指定路径）"
    ffmpeg = _ffmpeg_bin()
    if not ffmpeg:
        return False, "未找到 FFmpeg（yutto 混流必需，请在配置里指定路径）"

    # 轻量验证 yutto 能跑起来（--help 退出码非 0 属正常，只看是否有输出）
    try:
        kwargs = dict(capture_output=True, timeout=30, env=_build_env())
        if os.name == "nt":
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        r = subprocess.run([yutto, "--version"], **kwargs)
        out = (r.stdout or r.stderr or b"").decode("utf-8", "replace").strip()
        if out:
            return True, f"yutto 就绪（{out.splitlines()[0][:60]}），FFmpeg 可用"
        return True, f"yutto 可执行，FFmpeg 可用（{os.path.basename(ffmpeg)}）"
    except Exception as e:
        return False, f"yutto 运行异常: {str(e)[:160]}"


if __name__ == "__main__":
    import sys as _sys
    url = _sys.argv[1] if len(_sys.argv) > 1 else None
    if not url:
        print("用法: python bilibili_parser.py <bilibili视频链接>")
        _sys.exit(1)
    kind, paths = resolve_bilibili(url)
    print("下载完成:", kind, paths, "| 大小:", os.path.getsize(paths[0]), "字节")
