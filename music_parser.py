# -*- coding: utf-8 -*-
"""
网易云音乐 / QQ 音乐解析器（基于 yt-dlp）

支持：
  - 网易云音乐：music.163.com 长链、163cn.tv 短链
  - QQ 音乐：  y.qq.com 长链、c.y.qq.com 短链
返回：("audio", [本地 mp3/m4a 文件路径])
"""
import json
import os
import re
import sys
import tempfile
import time
import urllib.request

from core.config import get_config, VIDEO_DIR
from core.logger import logger


# ──────────────────────────────────────────────
# 辅助：解析 yt-dlp Python API（不走子进程）
# ──────────────────────────────────────────────
def _ydl_opts(out_dir: str, cookiefile: str = "") -> dict:
    """构造 yt-dlp 下载选项，优先选最佳音频，转为 mp3 输出。"""
    ffmpeg_path = _ffmpeg_path()
    postprocessors = [
        {
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "320",
        }
    ]
    opts = {
        "format": "bestaudio/best",
        "outtmpl": os.path.join(out_dir, "%(title)s.%(ext)s"),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "postprocessors": postprocessors,
        "socket_timeout": 30,
        "nocheckcertificate": True,
    }
    if ffmpeg_path:
        opts["ffmpeg_location"] = ffmpeg_path
    if cookiefile:
        opts["cookiefile"] = cookiefile
    return opts


def _cookie_file(cookie: str, domains):
    """
    把配置里粘贴的 Cookie 字符串（DevTools 的 `k=v; k2=v2` 头格式，或 .txt 文件路径）
    转成 yt-dlp 可用的 Netscape cookie 文件，返回临时文件路径；无法解析返回空串。

    domains: 该平台对应的域名列表（如 ["music.163.com"]），用于写入 cookie 的 domain 字段。
    """
    if not cookie:
        return ""
    cookie = cookie.strip()
    # 情况1：用户直接粘贴了 cookie 文件路径（该文件本身已是 Netscape 格式）
    if os.path.isfile(cookie):
        return cookie
    # 情况2：粘贴的是 `name=value; name2=value2` 头格式 → 转 Netscape
    pairs = {}
    for part in re.split(r"[;,]+\s*", cookie):
        if "=" in part:
            k, v = part.split("=", 1)
            pairs[k.strip()] = v.strip()
    if not pairs:
        return ""
    try:
        fd, path = tempfile.mkstemp(prefix="music_cookie_", suffix=".txt")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write("# Netscape HTTP Cookie File\n")
            # 未来过期时间（避免被当作过期会话丢弃）
            exp = "9999999999"
            for k, v in pairs.items():
                for dom in domains:
                    f.write("\t".join([dom, "TRUE", "/", "FALSE", exp, k, v]) + "\n")
        return path
    except Exception as e:
        logger.warning(f"[音乐] 生成 cookie 文件失败: {e}")
        return ""


def _ffmpeg_path() -> str:
    """探测 ffmpeg：先读配置，再查 tools/ffmpeg，最后走 PATH。"""
    # 1. 配置文件里写的路径（bilibili 共用的那个）
    try:
        cfg = get_config()
        p = cfg.get("bilibili", {}).get("ffmpeg_path", "")
        if p and os.path.isfile(p):
            return p
    except Exception:
        pass

    # 2. 项目内置 tools/ffmpeg/ffmpeg.exe
    base = os.path.dirname(os.path.abspath(__file__))
    candidate = os.path.join(base, "tools", "ffmpeg", "ffmpeg.exe")
    if os.path.isfile(candidate):
        return candidate

    # 3. 系统 PATH（返回空字符串，yt-dlp 会自己找）
    return ""


def _download(url: str, platform: str, out_dir: str, cookie: str = ""):
    """
    调用 yt-dlp 下载并后处理为 mp3，返回下载后的本地文件路径列表。
    若遇到版权限制 / VIP 限制 / 登录限制，抛出带友好说明的 RuntimeError。
    """
    try:
        import yt_dlp
    except ImportError:
        raise RuntimeError("yt-dlp 未安装，请运行: pip install yt-dlp")

    cookiefile = ""
    if cookie:
        domains = ["music.163.com", "163cn.tv"] if platform == "网易云" else ["y.qq.com", "c.y.qq.com", "u.y.qq.com"]
        cookiefile = _cookie_file(cookie, domains)
        if cookiefile:
            logger.info(f"[音乐][{platform}] 已启用 Cookie（{cookiefile}）")

    opts = _ydl_opts(out_dir, cookiefile=cookiefile)
    # 用 progress_hooks 捕获最终输出文件名
    downloaded_files = []

    def hook(d):
        if d.get("status") == "finished":
            fpath = d.get("filename") or d.get("info_dict", {}).get("filepath", "")
            if fpath:
                downloaded_files.append(fpath)

    opts["progress_hooks"] = [hook]

    logger.info(f"[音乐][{platform}] 开始下载: {url}")
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
    except yt_dlp.DownloadError as e:
        msg = str(e)
        # 把常见报错翻译成更友好的提示，避免程序卡死或无限重试
        if "registered users" in msg or "login" in msg.lower():
            hint = (f"[{platform}] 该歌曲需要登录后才能下载（VIP / 版权受限）。"
                    f"可在「配置中心 → {platform}」粘贴对应平台网页版 Cookie 后重试。")
        elif "record layer failure" in msg or "SSLError" in msg or "CertificateError" in msg:
            hint = (f"[{platform}] 无法建立到该平台服务器的安全连接（TLS/SSL 握手失败），"
                    f"通常是当前网络环境对该域名的限制，换用正常网络环境即可。")
        elif "copyright" in msg.lower() or "版权" in msg:
            hint = f"[{platform}] 该歌曲因版权受限无法下载。"
        else:
            hint = f"[{platform}] 解析失败：{msg[:160]}"
        logger.error(hint)
        raise RuntimeError(hint)
    finally:
        # 清理临时 cookie 文件
        if cookiefile and os.path.isfile(cookiefile) and cookiefile.startswith(tempfile.gettempdir()):
            try:
                os.remove(cookiefile)
            except Exception:
                pass

    # hook 路径可能是转码前的扩展名，统一修正为 .mp3
    result = []
    for fpath in downloaded_files:
        mp3_path = os.path.splitext(fpath)[0] + ".mp3"
        if os.path.isfile(mp3_path):
            result.append(mp3_path)
        elif os.path.isfile(fpath):
            result.append(fpath)

    # fallback：hook 没触发时，用 info 里的 filepath
    if not result and info:
        for key in ("filepath", "requested_downloads"):
            if key == "requested_downloads" and isinstance(info.get(key), list):
                for item in info[key]:
                    fp = item.get("filepath") or item.get("_filename", "")
                    mp3 = os.path.splitext(fp)[0] + ".mp3"
                    candidate = mp3 if os.path.isfile(mp3) else fp
                    if os.path.isfile(candidate):
                        result.append(candidate)
            else:
                fp = info.get(key, "")
                if fp:
                    mp3 = os.path.splitext(fp)[0] + ".mp3"
                    candidate = mp3 if os.path.isfile(mp3) else fp
                    if os.path.isfile(candidate):
                        result.append(candidate)

    if not result:
        # 扫描下载目录最新的 mp3 文件（最后兜底）
        candidates = sorted(
            [
                os.path.join(out_dir, f)
                for f in os.listdir(out_dir)
                if f.lower().endswith(".mp3")
            ],
            key=os.path.getmtime,
            reverse=True,
        )
        if candidates:
            result = [candidates[0]]

    if not result:
        raise RuntimeError(f"[{platform}] yt-dlp 下载完成但未找到音频文件")

    title = info.get("title", os.path.basename(result[0])) if info else os.path.basename(result[0])
    logger.info(f"[音乐][{platform}] 下载完成：《{title}》-> {result[0]}")
    return result


# ──────────────────────────────────────────────
# 短链还原
# ──────────────────────────────────────────────
def _expand_url(url: str) -> str:
    """跟随 HTTP 重定向还原短链，最多跟 5 跳。"""
    for _ in range(5):
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "Mozilla/5.0"},
                method="HEAD",
            )
            resp = urllib.request.urlopen(req, timeout=8)
            final = resp.url
            if final and final != url:
                url = final
            else:
                break
        except Exception:
            break
    return url


# ──────────────────────────────────────────────
# 网易云音乐
# ──────────────────────────────────────────────
_NETEASE_SONG_RE = re.compile(r"[?&/#]id[=/](\d+)")

# 网易云解析 API（开源 Suxiaoqinx/Netease_url 在线实例；可自托管，前端支持 localhost:3000）
_NETEASE_API_DEFAULT = "https://nextmusic.toubiec.cn"
_NETEASE_QUALITY_LEVELS = (
    "standard", "higher", "exhigh", "lossless", "hires", "sky", "jyeffect", "dolby", "clear",
)


def _netease_api_post(api_base: str, path: str, payload: dict, timeout: int = 25) -> dict:
    """POST 到网易云解析 API，返回解析后的 JSON dict（内含 code/data）。"""
    url = api_base.rstrip("/") + path
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _netease_api_get_ip(api_base: str) -> str:
    """调 /api/ip 拿到服务端要的公网 IP（接口必填字段）。"""
    r = _netease_api_post(api_base, "/api/ip", {"timestamp": int(time.time() * 1000)})
    if r.get("code") != 200 or not r.get("data", {}).get("ip"):
        raise RuntimeError(f"网易云 API 获取 IP 失败: {r.get('message', r)}")
    return r["data"]["ip"]


def _netease_api_song_url(api_base: str, song_id: str, quality: str, ip: str) -> str:
    """调 /api/getSongUrl 拿网易云 CDN 直链 mp3。"""
    payload = {
        "id": song_id,
        "level": quality if quality in _NETEASE_QUALITY_LEVELS else "standard",
        "timestamp": int(time.time() * 1000),
        "ip": ip,
    }
    r = _netease_api_post(api_base, "/api/getSongUrl", payload)
    if r.get("code") != 200 or not r.get("data", {}).get("url"):
        msg = r.get("message") or "无可用直链"
        raise RuntimeError(f"网易云 API 解析失败({r.get('code')}): {msg}")
    return r["data"]["url"]


def _netease_api_song_info(api_base: str, song_id: str, ip: str) -> dict:
    """调 /api/getSongInfo 拿歌名/歌手（用于生成文件名；失败返回空 dict，不影响主流程）。"""
    try:
        payload = {"id": song_id, "timestamp": int(time.time() * 1000), "ip": ip}
        r = _netease_api_post(api_base, "/api/getSongInfo", payload)
        if r.get("code") == 200 and r.get("data"):
            return r["data"]
    except Exception:
        pass
    return {}


def _safe_filename(name: str) -> str:
    """生成 Windows 安全的文件名（去除非法字符并限长）。"""
    name = (name or "").strip()
    if not name:
        return ""
    for ch in ('\\', '/', ':', '*', '?', '"', '<', '>', '|'):
        name = name.replace(ch, "_")
    return name[:120]


def _http_download(url: str, out_path: str, timeout: int = 60) -> None:
    """用 urllib 下载文件到 out_path（带分块写入与 Referer，规避网易云防盗链）。"""
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0", "Referer": "https://music.163.com/"},
    )
    total = 0
    with urllib.request.urlopen(req, timeout=timeout) as resp, open(out_path, "wb") as f:
        while True:
            chunk = resp.read(1024 * 256)
            if not chunk:
                break
            f.write(chunk)
            total += len(chunk)
    if total == 0:
        raise RuntimeError("网易云 API 直链下载到 0 字节")


def _netease_song_id(url: str) -> str:
    """从网易云各类链接中提取 song id（短链先跟随重定向还原）。"""
    work = url
    if "163cn.tv" in url or "/url" in url:
        work = _expand_url(url)
    m = _NETEASE_SONG_RE.search(work)
    if not m:
        raise RuntimeError(f"无法从链接中提取网易云歌曲 ID: {url}")
    return m.group(1)


def _resolve_netease_api(song_id: str, out_dir: str, quality: str, api_base: str):
    """走 API：拿直链 → 下载 mp3 → 返回 [本地路径]。"""
    ip = _netease_api_get_ip(api_base)
    cdn_url = _netease_api_song_url(api_base, song_id, quality, ip)
    info = _netease_api_song_info(api_base, song_id, ip)
    name = info.get("name") or ""
    singer = info.get("singer") or ""
    title = _safe_filename(f"{name} - {singer}".strip(" -")) or f"网易云_{song_id}"
    out_path = os.path.join(out_dir, title + ".mp3")
    # 避免重名覆盖：已存在则加序号
    base, ext = os.path.splitext(out_path)
    i = 1
    while os.path.exists(out_path):
        out_path = f"{base}({i}){ext}"
        i += 1
    logger.info(f"[音乐][网易云] API 下载《{title}》(quality={quality})")
    _http_download(cdn_url, out_path)
    logger.info(f"[音乐][网易云] API 下载完成 -> {out_path}")
    return [out_path]


def resolve_netease(url: str):
    """
    解析网易云音乐链接，下载音频，返回 ("audio", [文件路径])。

    解析策略（config.netease.source）：
      - auto  : API 优先（nextmusic.toubiec.cn），失败回退 yt-dlp
      - api   : 仅走 API
      - ytdlp : 仅走 yt-dlp（适合 API 不可用时）

    支持链接形态：
      - https://music.163.com/#/song?id=XXXX
      - https://music.163.com/song?id=XXXX
      - https://y.music.163.com/m/song?id=XXXX   （微信分享卡片常见形态）
      - https://163cn.tv/XXXX（短链，自动还原）
    """
    cfg = get_config()
    nc = cfg.get("netease", {})
    out_dir = nc.get("download_dir") or VIDEO_DIR
    cookie = nc.get("cookie", "") or ""
    source = str(nc.get("source", "auto")).strip() or "auto"
    quality = str(nc.get("quality", "exhigh")).strip() or "exhigh"
    api_base = str(nc.get("api_base", _NETEASE_API_DEFAULT)).strip() or _NETEASE_API_DEFAULT
    os.makedirs(out_dir, exist_ok=True)

    song_id = _netease_song_id(url)
    last_err = None

    # —— API 优先 ——
    if source in ("auto", "api"):
        try:
            files = _resolve_netease_api(song_id, out_dir, quality, api_base)
            return "audio", files
        except Exception as e:
            last_err = f"API: {e}"
            if source == "api":
                logger.error(f"[音乐][网易云] API 解析失败：{e}")
                raise RuntimeError(f"网易云 API 解析失败：{e}")
            logger.warning(f"[音乐][网易云] API 解析失败，回退 yt-dlp：{e}")

    # —— yt-dlp 兜底 ——
    if source in ("auto", "ytdlp"):
        try:
            real_url = url
            if "163cn.tv" in url or "/url" in url:
                real_url = _expand_url(url)
            files = _download(real_url, "网易云", out_dir, cookie=cookie)
            return "audio", files
        except Exception as e:
            last_err = f"yt-dlp: {e}"
            logger.error(f"[音乐][网易云] yt-dlp 解析也失败：{e}")

    raise RuntimeError(f"网易云解析失败：{last_err}")


# ──────────────────────────────────────────────
# QQ 音乐
# ──────────────────────────────────────────────
def resolve_qqmusic(url: str):
    """
    解析 QQ 音乐链接，下载音频，返回 ("audio", [文件路径])。
    支持：
      - https://y.qq.com/n/ryqq/songDetail/XXXX
      - https://c.y.qq.com/... (短链，自动还原)
      - 分享卡片里的 y.qq.com 链接
    """
    cfg = get_config()
    out_dir = cfg.get("qqmusic", {}).get("download_dir") or VIDEO_DIR
    cookie = cfg.get("qqmusic", {}).get("cookie", "") or ""
    os.makedirs(out_dir, exist_ok=True)

    # 短链还原
    if "c.y.qq.com" in url or "c6.y.qq.com" in url or len(url) < 60:
        url = _expand_url(url)

    files = _download(url, "QQ音乐", out_dir, cookie=cookie)
    return "audio", files


# ──────────────────────────────────────────────
# 统一入口
# ──────────────────────────────────────────────
def resolve_music(url: str, platform: str):
    """
    统一入口：按 platform 调用对应解析器。
    platform: "netease" | "qqmusic"
    返回: ("audio", [文件路径])
    """
    if platform == "netease":
        return resolve_netease(url)
    if platform == "qqmusic":
        return resolve_qqmusic(url)
    raise RuntimeError(f"music_parser: 未知平台 {platform!r}")


# ──────────────────────────────────────────────
# 环境测试
# ──────────────────────────────────────────────
def test_music_env() -> tuple:
    """检查 yt-dlp 与 ffmpeg 是否可用，返回 (ok, detail)。"""
    try:
        import yt_dlp
        version = yt_dlp.version.__version__
    except ImportError:
        return False, "yt-dlp 未安装，请运行: pip install yt-dlp"
    except Exception as e:
        return False, f"yt-dlp 加载失败: {e}"

    ffmpeg = _ffmpeg_path()
    if ffmpeg:
        ffmpeg_detail = f"ffmpeg: {ffmpeg}"
    else:
        # 尝试检查 PATH 里有没有
        import shutil
        if shutil.which("ffmpeg"):
            ffmpeg_detail = "ffmpeg: 已在 PATH 中找到"
        else:
            ffmpeg_detail = "ffmpeg: 未找到（mp3 转码将失败，建议配置 B站→ffmpeg 路径）"

    return True, f"yt-dlp {version} 就绪；{ffmpeg_detail}"


def test_netease_api(api_base: str = "") -> tuple:
    """
    测试网易云解析 API 是否可达且能正常解析一首歌（不下载文件）。
    返回 (ok, detail)。
    """
    base = api_base.strip() or _NETEASE_API_DEFAULT
    try:
        ip = _netease_api_get_ip(base)
        r = _netease_api_post(
            base, "/api/getSongUrl",
            {"id": "1403318151", "level": "standard", "timestamp": int(time.time() * 1000), "ip": ip},
        )
        if r.get("code") == 200 and r.get("data", {}).get("url"):
            return True, f"网易云 API 可达，解析正常（{base}）"
        return False, f"网易云 API 返回异常: {r.get('message', r)}"
    except Exception as e:
        return False, f"网易云 API 不可达: {e}"
