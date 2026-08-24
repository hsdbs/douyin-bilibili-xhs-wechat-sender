# -*- coding: utf-8 -*-
"""
B站视频解析与下载模块。

底层依赖：
  - yutto：轻量级 B站命令行下载器（基于 requests + ffmpeg）
  - ffmpeg：音视频混流（yutto 必需）
  - 登录 Cookie（SESSDATA）：可选。未提供时以游客态下载最高 480P/720P，
    提供 SESSDATA 后可下载 1080P/大会员专属画质。

入口函数：
  resolve_bilibili(url, download_dir=None) -> (kind, [file_paths])
    kind: "video"
    file_paths: 下载并混流完成的 mp4 文件路径列表（通常单元素）

异常：
  BilibiliParseError: 解析或下载失败时抛出

配置项（在 config/config.json 中 "bilibili" 段）：
  - enabled：平台开关（默认 True）
  - quality：清晰度代码（16=360P, 32=480P, 64=720P, 80=1080P，默认 64）
  - auth：B站 SESSDATA cookie（可选，高清/大会员需；留空游客态）
  - yutto_path：yutto 可执行文件路径（留空自动在 PATH/.venv 中探测）
  - ffmpeg_path：ffmpeg 可执行文件路径（留空自动探测）
  - timeout：下载超时秒数（默认 600）
  - max_retry：最大重试次数（默认 2）
"""
import glob
import os
import re
import shutil
import subprocess
import sys
import time

from core.config import get_config, VIDEO_DIR
from core.logger import logger

# B站链接正则：投稿视频 BV/av、短链 b23.tv、番剧/课程 ep/ss
BILIBILI_URL_RE = re.compile(
    r"https?://(?:www\.)?bilibili\.com/video/(?:BV[0-9A-Za-z]+|av\d+)(?:\?p=\d+)?/?|"
    r"https?://b23\.tv/[0-9A-Za-z]+/?|"
    r"https?://(?:www\.)?bilibili\.com/bangumi/play/(?:ep|ss)\d+|"
    r"https?://(?:www\.)?bilibili\.com/cheese/play/(?:ep|ss)\d+"
)


class BilibiliParseError(Exception):
    """B站解析/下载异常。"""
    pass


def _find_binary(name):
    """探测可执行文件路径：优先当前 Python 环境的 Scripts/，其次系统 PATH，最后内置 tools/。"""
    # 1. 当前虚拟环境
    scripts_dir = os.path.dirname(sys.executable)
    for ext in ("", ".exe", ".cmd", ".bat"):
        p = os.path.join(scripts_dir, name + ext)
        if os.path.isfile(p) and os.access(p, os.X_OK):
            return p
    # 2. 系统 PATH
    found = shutil.which(name)
    if found:
        return found
    # 3. 本地 tools/ 目录（打包或免安装分发时可能附带）
    base_dir = os.path.dirname(os.path.abspath(__file__))
    tool_p = os.path.join(base_dir, "tools", name, name + ".exe")
    if os.path.isfile(tool_p):
        return tool_p
    tool_p2 = os.path.join(base_dir, "tools", name + ".exe")
    if os.path.isfile(tool_p2):
        return tool_p2
    return None


def get_yutto_path():
    """获取 yutto 路径。"""
    cfg = get_config().get("bilibili", {})
    custom = cfg.get("yutto_path")
    if custom and os.path.isfile(custom):
        return custom
    p = _find_binary("yutto")
    if p:
        return p
    return "yutto"  # 尝试直接调用


def get_ffmpeg_path():
    """获取 ffmpeg 路径。"""
    cfg = get_config().get("bilibili", {})
    custom = cfg.get("ffmpeg_path")
    if custom and os.path.isfile(custom):
        return custom
    p = _find_binary("ffmpeg")
    if p:
        return p
    return "ffmpeg"


def _extract_url(text):
    """从文本中提取第一个 B站链接。"""
    m = BILIBILI_URL_RE.search(text or "")
    return m.group(0) if m else None


def resolve_bilibili(raw_text, download_dir=None):
    """解析并下载 B站视频。

    参数：
      raw_text: 包含 B站链接的文本（如分享消息或纯链接）
      download_dir: 下载保存目录，默认使用 config.VIDEO_DIR

    返回：
      (kind, [file_paths])
      kind: "video"
      file_paths: 下载生成的 mp4 文件绝对路径列表

    异常：
      BilibiliParseError: 下载失败或找不到产物文件
    """
    url = _extract_url(raw_text)
    if not url:
        raise BilibiliParseError(f"未从输入中提取到有效的 B站链接: {raw_text[:80]}")

    cfg = get_config().get("bilibili", {})
    out_dir = os.path.abspath(download_dir or cfg.get("download_dir") or VIDEO_DIR)
    os.makedirs(out_dir, exist_ok=True)

    quality = int(cfg.get("quality", 64))
    auth = (cfg.get("auth") or "").strip()
    timeout = int(cfg.get("timeout", 600))
    max_retry = int(cfg.get("max_retry", 2))

    yutto = get_yutto_path()
    ffmpeg = get_ffmpeg_path()

    # 记录下载前目录中已有的 mp4 文件（用于识别新生成的文件）
    before_files = set(glob.glob(os.path.join(out_dir, "*.mp4")))

    # 构建 yutto 命令
    # yutto <url> -d <dir> -q <quality> --no-color --no-progress
    # 可选 SESSDATA cookie: -c "SESSDATA=..."
    # 额外指定 ffmpeg 路径环境变量
    cmd = [
        yutto,
        url,
        "-d", out_dir,
        "-q", str(quality),
        "--no-color",
        "--no-progress",
        "--batch=false",      # 只下载单 P，防止多 P 合集一次性全下爆磁盘
    ]
    if auth:
        # 如果用户只填了纯 SESSDATA 串，自动补齐键名
        cookie_val = auth if "SESSDATA=" in auth else f"SESSDATA={auth}"
        cmd.extend(["-c", cookie_val])

    # 环境变量准备（注入 ffmpeg 所在目录到 PATH 前端）
    env = os.environ.copy()
    if ffmpeg and os.path.isabs(ffmpeg):
        ff_dir = os.path.dirname(ffmpeg)
        env["PATH"] = ff_dir + os.pathsep + env.get("PATH", "")

    logger.info(f"[B站解析] 开始下载: url={url} quality={quality} dir={out_dir}")

    last_err = None
    for attempt in range(1, max_retry + 1):
        try:
            t0 = time.time()
            # Windows 下隐藏控制台窗口
            creationflags = 0
            if sys.platform == "win32":
                creationflags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0x08000000

            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                env=env,
                creationflags=creationflags,
            )
            elapsed = time.time() - t0

            if proc.returncode != 0:
                err_msg = (proc.stderr or proc.stdout or "").strip()
                # 提取有价值的错误行
                err_lines = [l for l in err_msg.splitlines() if "error" in l.lower() or "exception" in l.lower()]
                detail = " | ".join(err_lines[-3:]) if err_lines else err_msg[-200:]
                last_err = f"yutto 返回码 {proc.returncode}: {detail}"
                logger.warning(f"[B站解析] 第 {attempt}/{max_retry} 次失败: {last_err}")
                if attempt < max_retry:
                    time.sleep(2)
                continue

            # 探测新生成的 mp4 文件
            after_files = set(glob.glob(os.path.join(out_dir, "*.mp4")))
            new_files = list(after_files - before_files)

            if not new_files:
                # 兜底：按修改时间找最近 60 秒内更新的 mp4
                recent = []
                now = time.time()
                for f in after_files:
                    try:
                        if now - os.path.getmtime(f) < max(60, elapsed + 10):
                            recent.append(f)
                    except Exception:
                        pass
                if recent:
                    recent.sort(key=lambda x: os.path.getmtime(x), reverse=True)
                    new_files = [recent[0]]

            if not new_files:
                last_err = f"下载完成但未在 {out_dir} 找到新生成的 mp4 文件"
                logger.warning(f"[B站解析] 第 {attempt}/{max_retry} 次: {last_err}")
                continue

            target_file = new_files[0]
            size_mb = os.path.getsize(target_file) / 1024 / 1024
            logger.info(f"[B站解析] 下载成功: {os.path.basename(target_file)} ({size_mb:.2f} MB, 耗时 {elapsed:.1f}s)")
            return ("video", [os.path.abspath(target_file)])

        except subprocess.TimeoutExpired:
            last_err = f"下载超时（超过 {timeout} 秒）"
            logger.warning(f"[B站解析] 第 {attempt}/{max_retry} 次超时")
        except FileNotFoundError:
            raise BilibiliParseError(
                f"未找到 yutto 下载工具（路径: {yutto}）。"
                f"请在虚拟环境中安装: pip install yutto；或在 Web「配置中心」填写完整路径。"
            )
        except Exception as e:
            last_err = str(e)
            logger.warning(f"[B站解析] 第 {attempt}/{max_retry} 次异常: {e}")

        if attempt < max_retry:
            time.sleep(2)

    raise BilibiliParseError(f"B站视频下载失败（重试 {max_retry} 次）: {last_err}")


def test_bilibili():
    """连通性与依赖自检：检测 yutto 与 ffmpeg 是否可用。返回 (ok, detail)。"""
    yutto = get_yutto_path()
    ffmpeg = get_ffmpeg_path()

    yutto_ok = False
    yutto_ver = ""
    try:
        res = subprocess.run([yutto, "--version"], capture_output=True, text=True, timeout=5)
        if res.returncode == 0:
            yutto_ok = True
            yutto_ver = (res.stdout or "").strip().splitlines()[0] if res.stdout else "已安装"
    except Exception:
        yutto_ok = False

    ffmpeg_ok = False
    ffmpeg_ver = ""
    try:
        res = subprocess.run([ffmpeg, "-version"], capture_output=True, text=True, timeout=5)
        if res.returncode == 0:
            ffmpeg_ok = True
            m = re.search(r"ffmpeg version\s+([^\s]+)", res.stdout or "")
            ffmpeg_ver = m.group(1) if m else "已安装"
    except Exception:
        ffmpeg_ok = False

    if yutto_ok and ffmpeg_ok:
        return True, f"yutto ({yutto_ver}) + ffmpeg ({ffmpeg_ver}) 就绪"
    elif not yutto_ok and not ffmpeg_ok:
        return False, "缺少 yutto 与 ffmpeg（需 pip install yutto 并安装 ffmpeg）"
    elif not yutto_ok:
        return False, f"缺少 yutto（ffmpeg: {ffmpeg_ver}，需 pip install yutto）"
    else:
        return False, f"缺少 ffmpeg（yutto: {yutto_ver}，音视频混流需 ffmpeg）"
