# -*- coding: utf-8 -*-
"""
抖音无水印视频 / 图文解析 + 下载模块

基于 f2 (Johnserf-Seed/TikTokDownload)：
  分享链接 → AwemeIdFetcher.get_aweme_id → DouyinHandler.fetch_one_video
  → 视频（aweme_type 0/55/61/109/201）：video_play_addr（无水印直链）→ httpx 下载 mp4
  → 图文（aweme_type=68）：images → 下载多张图并用 Pillow 转 jpg

依赖：f2、httpx、Pillow（已在项目 .venv）。
下载目录 / 重试参数由 config/config.json 统一管理（可在 Web 面板配置）。
Cookie：每次解析时自动抓取游客态 Cookie（ttwid + msToken），无需用户手动填写。
"""
import asyncio
import os
import time
import logging

import httpx

from f2.apps.douyin.handler import DouyinHandler
from f2.apps.douyin.utils import AwemeIdFetcher, TokenManager
from f2.apps.bark.utils import ClientConfManager as _BarkConf

from core.config import get_config, VIDEO_DIR

# 禁用 Bark 通知（f2 默认开启，会往 api.day.app 发通知报 405 噪音）
_BarkConf.client_conf["enable_bark"] = False
# 静音 f2 的日志（logger 名 "f2"，标准 logging）
logging.getLogger("f2").setLevel(logging.CRITICAL)

# 测试用链接（抖音分享短链）
DEFAULT_TEST_URL = "https://v.douyin.com/UoTgR_eqR8Y/"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36")


def _gen_guest_cookie():
    """每次解析时自动抓取游客态 Cookie（设备指纹 ttwid + 随机 msToken 兜底）。

    抖音公开作品无需登录即可获取，游客态 Cookie 已足够，无需用户手动填写。
    ttwid 通过 f2 的 TokenManager 向抖音接口实时申请；msToken 由模型层自动生成，
    这里再补一个随机值提高成功率。生成失败返回空字符串（f2 仍会尝试请求）。
    """
    parts = []
    try:
        ttwid = TokenManager.gen_ttwid()
        if ttwid:
            parts.append(f"ttwid={ttwid}")
    except Exception:
        pass
    try:
        ms = TokenManager.gen_false_msToken()
        if ms:
            parts.append(f"msToken={ms}")
    except Exception:
        pass
    return "; ".join(parts)


def _download_dir():
    try:
        d = get_config().get("douyin", {}).get("download_dir") or ""
        if d:
            return d
    except Exception:
        pass
    return VIDEO_DIR


def _max_retry():
    try:
        return int(get_config().get("douyin", {}).get("max_retry", 3))
    except Exception:
        return 3


def _retry_interval():
    try:
        return int(get_config().get("douyin", {}).get("retry_interval", 4))
    except Exception:
        return 4


def _kwargs():
    return {
        "headers": {"User-Agent": UA, "Referer": "https://www.douyin.com/"},
        "cookie": _gen_guest_cookie(),
        "proxies": {"http://": None, "https://": None},
    }


async def _parse_detail(url):
    """解析抖音分享链接，返回作品详情 dict（含 aweme_type / video_play_addr / images 等）。

    用 aweme_type 区分作品类型：视频类 [0,55,61,109,201]，图文类 68。
    """
    aweme_id = await AwemeIdFetcher.get_aweme_id(url)
    video = await DouyinHandler(_kwargs()).fetch_one_video(aweme_id=aweme_id)
    return video._to_dict()


def _sanitize(name):
    """清理文件名中的非法字符。"""
    for ch in '\\/:*?"<>|':
        name = name.replace(ch, "_")
    return name.strip() or "video"


async def _download(addrs, filename):
    """从直链列表依次尝试下载，返回本地文件路径。"""
    download_dir = _download_dir()
    os.makedirs(download_dir, exist_ok=True)
    headers = {"User-Agent": UA, "Referer": "https://www.douyin.com/"}
    async with httpx.AsyncClient(headers=headers, follow_redirects=True, timeout=120) as c:
        for i, addr in enumerate(addrs):
            try:
                r = await c.get(addr)
                if r.status_code == 200 and len(r.content) > 1000:
                    path = os.path.join(download_dir, filename)
                    with open(path, "wb") as f:
                        f.write(r.content)
                    return path
            except Exception as e:
                logging.warning("下载第 %d 个地址失败: %s", i + 1, e)
    raise RuntimeError("所有视频地址下载均失败")


def _save_image(content, path):
    """用 Pillow 把图片内容（webp/jpeg/png 等）统一转成 jpg 保存，兼容微信展示。"""
    try:
        import io
        from PIL import Image
        img = Image.open(io.BytesIO(content))
        img = img.convert("RGB")
        img.save(path, "JPEG", quality=90)
    except Exception:
        # 转码失败则直接落原始字节
        with open(path, "wb") as f:
            f.write(content)


async def _download_images(img_urls, title, author):
    """下载图文的多张图片，返回本地图片路径列表。"""
    download_dir = _download_dir()
    os.makedirs(download_dir, exist_ok=True)
    base = _sanitize(f"{title}_{author}")
    headers = {"User-Agent": UA, "Referer": "https://www.douyin.com/"}
    paths = []
    async with httpx.AsyncClient(headers=headers, follow_redirects=True, timeout=120) as c:
        for i, addr in enumerate(img_urls):
            try:
                r = await c.get(addr)
                if r.status_code != 200 or len(r.content) <= 1000:
                    continue
                path = os.path.join(download_dir, f"{base}_{i + 1}.jpg")
                _save_image(r.content, path)
                paths.append(path)
            except Exception as e:
                logging.warning("下载第 %d 张图片失败: %s", i + 1, e)
    if not paths:
        raise RuntimeError("所有图片下载均失败")
    return paths


def resolve_douyin(url):
    """统一同步入口：解析抖音链接（视频或图文）并下载，返回 (kind, file_paths)。

    kind: "video"=视频 | "note"=图文；
    file_paths: 本地文件路径列表（视频 1 个 mp4，图文 N 张 jpg）。
    遇到 403/风控时自动重试（抖音风控多为临时性）。
    """
    max_retry = _max_retry()
    retry_interval = _retry_interval()
    last_err = None
    for attempt in range(max_retry):
        try:
            d = asyncio.run(_parse_detail(url))
            title = (d.get("desc") or "").strip()[:30]
            author = (d.get("nickname") or "unknown")
            aweme_type = int(d.get("aweme_type") or 0)

            if aweme_type == 68:  # 图文
                img_urls = d.get("images") or []
                if not img_urls:
                    raise RuntimeError("图文作品未获取到图片")
                return "note", asyncio.run(_download_images(img_urls, title, author))

            # 视频
            addrs = d.get("video_play_addr") or []
            if not addrs:
                raise RuntimeError("未获取到视频下载地址（可能是不支持的作品类型）")
            filename = f"{_sanitize(title)}_{author}.mp4"
            return "video", [asyncio.run(_download(addrs, filename))]
        except Exception as e:
            last_err = e
            msg = str(e)
            if attempt < max_retry - 1:
                print(f"[解析] 第 {attempt + 1} 次失败({msg[:60]})，{retry_interval}s 后重试...")
                time.sleep(retry_interval)
    raise last_err


def resolve_douyin_video(url):
    """视频专用入口（向后兼容）：只返回视频 mp4 路径；图文会抛错。"""
    kind, paths = resolve_douyin(url)
    if kind != "video":
        raise RuntimeError("该链接是图文作品，不是视频")
    return paths[0]


def test_douyin(test_url=None):
    """测试抖音解析连通性：自动抓取游客态 Cookie 并尝试解析作品。返回 (ok, detail)。"""
    url = test_url or DEFAULT_TEST_URL
    try:
        d = asyncio.run(_parse_detail(url))
        title = (d.get("desc") or "").strip()[:30]
        aweme_type = int(d.get("aweme_type") or 0)
        kind = "图文" if aweme_type == 68 else "视频"
        return True, f"游客态解析正常，{kind}作品：{title}"
    except Exception as e:
        return False, f"解析失败: {str(e)[:120]}"


if __name__ == "__main__":
    test_url = DEFAULT_TEST_URL
    p = resolve_douyin_video(test_url)
    print("下载完成:", p, "| 大小:", os.path.getsize(p), "字节")
