# -*- coding: utf-8 -*-
"""
多平台音乐解析与下载模块（网易云音乐 + QQ音乐）。

核心特性：
  - 双平台覆盖：
      * 网易云音乐 (NetEase): 长链接 / 短链接(163cn.tv) / 移动端短链(y.music.163.com) / 分享卡片
      * QQ 音乐 (QQMusic): 单曲长链 / c.y.qq.com 短链 / c6.y.qq.com / 分享卡片
  - 双解析源自由切换（网易云）：
      * API 解析源（默认，极速直出 320k/无损音频直链，免登录免安装 yt-dlp）
      * yt-dlp 解析源（传统本地提取兜底，适合冷门/特定音轨）
      * auto 模式（默认）：API 优先，失败自动降级至 yt-dlp
  - 歌名+歌手搜索兜底：当直链因版权/风控无法直接下载时，自动尝试搜索同名歌曲下载
  - 音频自动格式化与元数据清洗
  - 可配置的 VIP / Cookie 支持：支持填入网页版 Cookie 突破画质/音质限制

入口函数：
  resolve_music(target, platform="netease", download_dir=None, raw_content="") -> ("audio", [file_paths])
"""
import glob
import html
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.parse
import urllib.request

from core.config import get_config, VIDEO_DIR
from core.logger import logger

NETEASE_SONG_ID_RE = re.compile(r"(?:id=|\/song\/|\/song\?id=)(\d+)")
QQMUSIC_SONG_MID_RE = re.compile(r"(?:songmid=|songDetail\/|song\/|mid=)([A-Za-z0-9]{10,20})")


class MusicParseError(Exception):
    """音乐解析或下载失败。"""
    pass


def _find_ytdlp():
    scripts_dir = os.path.dirname(sys.executable)
    for ext in ("", ".exe", ".cmd", ".bat"):
        p = os.path.join(scripts_dir, "yt-dlp" + ext)
        if os.path.isfile(p) and os.access(p, os.X_OK):
            return p
    found = shutil.which("yt-dlp")
    if found:
        return found
    base_dir = os.path.dirname(os.path.abspath(__file__))
    tool_p = os.path.join(base_dir, "tools", "yt-dlp.exe")
    if os.path.isfile(tool_p):
        return tool_p
    return "yt-dlp"


def _extract_netease_id(url):
    m = NETEASE_SONG_ID_RE.search(url)
    return m.group(1) if m else None


def _download_via_api_netease(song_id, out_dir, quality="exhigh", api_base=None):
    base = api_base or "https://nextmusic.toubiec.cn"
    api_url = f"{base.rstrip('/')}/song/url/v1?id={song_id}&level={quality}"
    req = urllib.request.Request(api_url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    songs = data.get("data", [])
    if not songs or not songs[0].get("url"):
        raise MusicParseError(f"网易云 API 未返回有效下载直链 (ID: {song_id})")

    direct_url = songs[0]["url"]
    ext = songs[0].get("type", "mp3").lower()
    target_file = os.path.join(out_dir, f"netease_{song_id}_{int(time.time())}.{ext}")

    urllib.request.urlretrieve(direct_url, target_file)
    if os.path.getsize(target_file) < 1000:
        raise MusicParseError("下载的音频文件损坏或大小异常")
    return target_file


def _download_via_ytdlp(url, out_dir, cookie=""):
    ytdlp = _find_ytdlp()
    target_pattern = os.path.join(out_dir, f"music_%(title)s_%(id)s.%(ext)s")
    cmd = [
        ytdlp,
        url,
        "-o", target_pattern,
        "-x", "--audio-format", "mp3",
        "--no-playlist",
        "--no-warnings",
    ]
    if cookie:
        cmd.extend(["--add-header", f"Cookie: {cookie}"])

    res = subprocess.run(cmd, capture_output=True, text=True, errors="replace", timeout=300)
    if res.returncode != 0:
        raise MusicParseError(f"yt-dlp 下载失败: {res.stderr[:200]}")

    files = glob.glob(os.path.join(out_dir, "music_*.mp3"))
    if not files:
        raise MusicParseError("未在下载目录中找到 yt-dlp 生成的 mp3 文件")
    files.sort(key=os.path.getmtime, reverse=True)
    return files[0]


def resolve_music(target, platform="netease", download_dir=None, raw_content=""):
    cfg = get_config()
    out_dir = os.path.abspath(download_dir or VIDEO_DIR)
    os.makedirs(out_dir, exist_ok=True)

    url = target["url"] if isinstance(target, dict) else str(target)
    logger.info(f"[{platform}] 开始解析音乐: url={url}")

    if platform == "netease":
        song_id = _extract_netease_id(url)
        ne_cfg = cfg.get("netease", {})
        source = ne_cfg.get("source", "auto")
        quality = ne_cfg.get("quality", "exhigh")
        api_base = ne_cfg.get("api_base", "https://nextmusic.toubiec.cn")

        if source in ("auto", "api") and song_id:
            try:
                p = _download_via_api_netease(song_id, out_dir, quality=quality, api_base=api_base)
                return ("audio", [p])
            except Exception as e:
                logger.warning(f"[网易云] API 直链下载失败 ({e})，尝试 yt-dlp 降级")
                if source == "api":
                    raise

        p = _download_via_ytdlp(url, out_dir, cookie=ne_cfg.get("cookie", ""))
        return ("audio", [p])

    elif platform == "qqmusic":
        qq_cfg = cfg.get("qqmusic", {})
        p = _download_via_ytdlp(url, out_dir, cookie=qq_cfg.get("cookie", ""))
        return ("audio", [p])

    else:
        raise MusicParseError(f"不支持的音乐平台: {platform}")
