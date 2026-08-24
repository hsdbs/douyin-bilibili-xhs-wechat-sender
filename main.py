# -*- coding: utf-8 -*-
"""
抖音链接 → 解析 → 自动发送视频（端到端主程序）

数据流：
  主动推送（SSE）+ 轮询兜底 → 识别消息中的链接 → 确定接收者 → 解析视频 → wxauto4 发送

业务逻辑保持不变，配置已迁移到 config/config.json（Web 面板可改），
日志统一走 core.logger，主循环封装为可停止的 worker（供 Web 服务控制）。

安全策略：
  - 私聊：正常处理，发给对方
  - 群聊：仅白名单内的群发到群里，其余忽略
  - 测试模式（test_mode）：所有发送统一发到「文件传输助手」

去重机制：消息级 rawid 去重（data/processed_rawids.json，推送事件自带 rawid）。

监听方式（可在 Web「高级设置」切换）：
  - 主动推送（listen_push）：订阅 WeFlow SSE，实时、低延迟；但收不到「自己发送」的消息。
  - 轮询兜底（listen_poll）：定时拉取会话消息，覆盖推送漏掉的消息（含自己发送的）。
  两者可同时开启（默认），共用同一套 rawid 去重，不会重复处理。
"""
import ctypes
import html
import json
import os
import queue
import re
import threading
import time
import traceback
import urllib.request

from mapping import _base_url, _get, _token, load_mapping, resolve_display_name

from core.config import get_config, DATA_DIR, VIDEO_DIR, BASE_DIR
from core.logger import logger
from core import tasks, state

# ============ 运行时配置（由 _apply_config 从 config.json 刷新）============
PARSE_MODE = "real"          # "fake"=测试视频占位；"real"=真实解析（douyin_parser）

GROUP_WHITELIST = []         # 群聊白名单（wxid 或显示名）
TEST_MODE = False            # True=所有发送发到「文件传输助手」

# 监听方式开关（可在 Web「高级设置」切换，运行时随配置刷新）
LISTEN_PUSH = True           # 启用 WeFlow 主动推送（SSE，实时）
LISTEN_POLL = True           # 启用轮询兜底（可监听到自己发送的消息）
POLL_INTERVAL = 3            # 轮询间隔（秒）
LOOKBACK_LIMIT = 10          # 每会话扫描最近 N 条消息
ACTIVE_WINDOW = 86400        # 只看最近 N 秒内有消息的会话

DELETE_AFTER_SECONDS = 180   # 发送后延迟删除（秒）。默认 180=3 分钟；设 0 或负数则永不删除
DOWNLOAD_DIR = VIDEO_DIR     # 下载目录（仅清理此目录内文件）
QUOTE_REPLY = True           # True=发送视频/图文时引用对方消息
DELETE_QUEUE_FILE = os.path.join(DATA_DIR, "pending_deletions.json")
PROCESSED_FILE = os.path.join(DATA_DIR, "processed_rawids.json")

SSE_READ_TIMEOUT = 60        # SSE 读超时（秒）：须大于 WeFlow 心跳间隔（实测约 25s），
                             # 仅用于探测连接失活（无心跳且未断开）；停止响应由主循环 stop_event 即时处理

# 抖音链接正则（覆盖短链、视频页、分享链接）
DOUYIN_URL_RE = re.compile(
    r"https?://(?:v\.douyin\.com/[\w\-]+/?|"
    r"www\.douyin\.com/(?:video|note)/\d+|"
    r"www\.iesdouyin\.com/share/(?:video|note)/\d+)"
)

# B站链接正则（投稿视频 BV/av、短链 b23.tv、番剧/课程 ep/ss）
BILIBILI_URL_RE = re.compile(
    r"https?://(?:www\.)?bilibili\.com/video/(?:BV[0-9A-Za-z]+|av\d+)(?:\?p=\d+)?/?|"
    r"https?://b23\.tv/[0-9A-Za-z]+/?|"
    r"https?://(?:www\.)?bilibili\.com/bangumi/play/(?:ep|ss)\d+|"
    r"https?://(?:www\.)?bilibili\.com/cheese/play/(?:ep|ss)\d+"
)

# 小红书链接正则（explore / discovery/item / rednote / xhslink 短链，含 xsec_token 查询串）
# 注意：xhslink 短链形如 xhslink.cn/o/AbCdEf123（多段路径），需用 [A-Za-z0-9/]+ 捕获完整路径，
#       否则会被截断成 xhslink.cn/o 导致解析失败。
XHS_URL_RE = re.compile(
    r"https?://(?:www\.)?(?:xiaohongshu\.com|rednote\.com)/"
    r"(?:explore|discovery/item)/[A-Za-z0-9]+(?:[?&][A-Za-z0-9_%=\-&]+)?|"
    r"https?://xhslink\.(?:com|cn)/[A-Za-z0-9/]+"
)

# 网易云音乐链接正则（PC 长链 + m 站移动端短链 y.music.163.com + 163cn.tv 短链）
# 注：微信分享卡片里的网易云链接多为 y.music.163.com/m/song?id=xxxx 形态
NETEASE_URL_RE = re.compile(
    r"https?://(?:"
    r"music\.163\.com/(?:#/)?(?:song|album|playlist|artist|dj)[^\s'\"<>]*|"
    r"y\.music\.163\.com/[^\s'\"<>]+|"
    r"163cn\.tv/[A-Za-z0-9]+/?)"
)

# QQ 音乐链接正则（y.qq.com 长链 + c.y.qq.com / c6.y.qq.com 短链）
QQMUSIC_URL_RE = re.compile(
    r"https?://(?:y\.qq\.com/[^\s'\"<>]+|"
    r"c(?:6)?\.y\.qq\.com/[^\s'\"<>]+)"
)

# 平台 → 链接正则（按顺序匹配，命中第一个即归属该平台）
PLATFORM_URL_RES = [
    ("douyin", DOUYIN_URL_RE),
    ("bilibili", BILIBILI_URL_RE),
    ("xhs", XHS_URL_RE),
    ("netease", NETEASE_URL_RE),
    ("qqmusic", QQMUSIC_URL_RE),
]

# 命令正则：./下载 书名（维基文库公有资源下载，兼容中英文标点、书名号与多余空格）
COMMAND_RE = re.compile(r"^[.·。/、\s]*下载\s*[：:]?\s*《?([^》\r\n]+)》?\s*$", re.IGNORECASE)

PLATFORM_NAMES = {"douyin": "抖音", "bilibili": "B站", "xhs": "小红书",
                  "netease": "网易云音乐", "qqmusic": "QQ音乐",
                  "wikisource": "电子书", "novel": "电子书", "ebook": "电子书"}


def _match_book_command(content):
    """严格按照 Web 配置中用户设定的触发指令前缀匹配电子书下载请求。"""
    try:
        cfg = get_config()
        ebook_cfg = cfg.get("ebook", {})
        if not ebook_cfg.get("enabled", True):
            return None

        # 严格读取用户在 Web 界面设定的指令前缀（若空则默认 ./下载）
        prefix = (ebook_cfg.get("command_prefix") or "./下载").strip()
        if not prefix:
            return None

        raw = (content or "").strip()

        # 严格匹配以用户自定义 prefix 开头的消息，后接可选的空格/冒号以及书名
        pattern = r"^\s*" + re.escape(prefix) + r"\s*[：:]?\s*《?([^》\r\n]+)》?\s*$"
        m = re.search(pattern, raw, re.IGNORECASE)
        if m:
            title = m.group(1).strip().strip("《》").strip()
            if title:
                return title
    except Exception as e:
        logger.error(f"[电子书指令] 匹配异常: {e}")
    return None


def detect_card(content):
    """识别分享卡片（XML appmsg）并提取反转义后的完整链接与标题。

    返回 dict {"url": <反转义完整链接>, "title": <卡片标题>, "platform": <平台键>} 或 None：
      - content 不是卡片 / 不含 <appmsg> 结构 -> None（交给原文本正则路径）
      - 是卡片但 <url> 域名不属于已知平台 -> None（暂不处理其它来源卡片）
      - 是已知平台卡片 -> 返回完整反转义链接（保留解析必需参数）+ 标题 + 平台

    覆盖平台：小红书（xiaohongshu/rednote/xhslink）、B站（bilibili/b23.tv）、
    网易云音乐（music.163.com / y.music.163.com / 163cn.tv）、QQ音乐（y.qq.com / c.y.qq.com）。
    背景：微信里分享卡片是结构化消息，真实链接在 <appmsg><url> 字段中，且 XML 对 &
    做转义（&amp;）。现有纯文本正则会因参数中的 '.' 之类字符截断、丢失关键参数，因此卡片
    单独走此分支——直接从 XML <url> 取完整链接并用 html.unescape 反转义，不去碰既有正则。
    title 取自 <title>（音乐卡片里是歌名），singer 取自 <des>（音乐卡片里是歌手）；
    二者用于发送时引用原卡片，以及作为「歌名+歌手」搜索下载的候选输入。
    """
    if not content or "<appmsg" not in content or "<url" not in content:
        return None
    m = re.search(r"<url>(.*?)</url>", content, re.DOTALL | re.IGNORECASE)
    if not m:
        return None
    url = html.unescape(m.group(1).strip())

    platform = None
    if (re.search(r"https?://(?:www\.)?(?:xiaohongshu\.com|rednote\.com)/", url)
            or re.search(r"https?://xhslink\.(?:com|cn)/", url)):
        platform = "xhs"
    elif (re.search(r"https?://(?:www\.|m\.)?bilibili\.com/", url)
          or re.search(r"https?://b23\.tv/", url)):
        platform = "bilibili"
    elif re.search(r"https?://(?:music\.163\.com|y\.music\.163\.com|163cn\.tv)/", url):
        platform = "netease"
    elif re.search(r"https?://(?:y\.qq\.com|c(?:6)?\.y\.qq\.com)/", url):
        platform = "qqmusic"
    if not platform:
        return None

    # 卡片标题（音乐卡片里是歌名），用于发送时引用原卡片
    title = None
    mt = re.search(r"<title>(.*?)</title>", content, re.DOTALL | re.IGNORECASE)
    if mt:
        title = html.unescape(mt.group(1).strip())
    # 卡片歌手（音乐卡片里是 <des> 字段，部分旧版可能用 <description>），
    # 作为「歌名+歌手」搜索下载的候选输入（URL 解析失败时的兜底）
    singer = None
    md = re.search(r"<des>(.*?)</des>", content, re.DOTALL | re.IGNORECASE)
    if not md:
        md = re.search(r"<description>(.*?)</description>", content, re.DOTALL | re.IGNORECASE)
    if md:
        singer = html.unescape(md.group(1).strip())
    return {"url": url, "title": title, "singer": singer, "platform": platform}


def _platform_enabled(platform):
    """读取某平台 enabled 开关（默认 True）。"""
    try:
        cfg = get_config()
        if platform in ("wikisource", "novel", "ebook"):
            return bool(cfg.get("ebook", {}).get("enabled", True))
        return bool(cfg.get(platform, {}).get("enabled", True))
    except Exception:
        return True


def _apply_config():
    """把 config.json 的最新值刷新到模块级运行时变量。"""
    global PARSE_MODE
    global GROUP_WHITELIST, TEST_MODE, DELETE_AFTER_SECONDS, DOWNLOAD_DIR, QUOTE_REPLY
    global LISTEN_PUSH, LISTEN_POLL, POLL_INTERVAL, LOOKBACK_LIMIT, ACTIVE_WINDOW
    try:
        cfg = get_config()
        dy = cfg.get("douyin", {})
        PARSE_MODE = dy.get("parse_mode", "real") or "real"
        DOWNLOAD_DIR = dy.get("download_dir") or VIDEO_DIR
        wc = cfg.get("wechat", {})
        GROUP_WHITELIST = list(wc.get("group_whitelist") or [])
        TEST_MODE = bool(wc.get("test_mode", False))
        DELETE_AFTER_SECONDS = int(wc.get("delete_after_seconds", 180))
        QUOTE_REPLY = bool(wc.get("quote_reply", True))
        adv = cfg.get("advanced", {})
        LISTEN_PUSH = bool(adv.get("listen_push", True))
        LISTEN_POLL = bool(adv.get("listen_poll", True))
        POLL_INTERVAL = int(adv.get("poll_interval", 3)) or 3
        LOOKBACK_LIMIT = int(adv.get("lookback_limit", 10)) or 10
        ACTIVE_WINDOW = int(adv.get("active_window", 86400)) or 86400
    except Exception as e:
        logger.error(f"[配置] 读取配置失败，使用默认值: {e}")


# ============ 已处理消息 rawid 去重 ============
def load_processed():
    if not os.path.exists(PROCESSED_FILE):
        return set()
    try:
        with open(PROCESSED_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return set(data if isinstance(data, list) else [])
    except Exception:
        return set()


def save_processed(rawids):
    # 注意：须在 _processed_lock 持有时调用（内部对 rawids 排序遍历，需防并发改集合）
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(PROCESSED_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted(rawids), f, ensure_ascii=False, indent=2)


_processed_lock = threading.Lock()
_processed_rawids = load_processed()
_processed_modified = False


def is_processed(rawid):
    if rawid is None:
        return False
    with _processed_lock:
        return rawid in _processed_rawids


def mark_processed(rawid):
    global _processed_modified
    if rawid is None:
        return
    with _processed_lock:
        _processed_rawids.add(rawid)
        _processed_modified = True


def flush_processed_if_needed():
    global _processed_modified
    with _processed_lock:
        if _processed_modified:
            try:
                save_processed(_processed_rawids)
                _processed_modified = False
            except Exception as e:
                logger.error(f"[去重] 写入 processed_rawids 失败: {e}")


# ============ 延迟删除队列 ============
_delete_lock = threading.Lock()


def load_delete_queue():
    if not os.path.exists(DELETE_QUEUE_FILE):
        return []
    try:
        with open(DELETE_QUEUE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def save_delete_queue(q):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(DELETE_QUEUE_FILE, "w", encoding="utf-8") as f:
        json.dump(q, f, ensure_ascii=False, indent=2)


def schedule_deletion(file_paths, delay_seconds=180):
    if delay_seconds <= 0:
        return
    delete_at = time.time() + delay_seconds
    with _delete_lock:
        q = load_delete_queue()
        for fp in file_paths:
            q.append({"path": os.path.abspath(fp), "delete_at": delete_at})
        save_delete_queue(q)
    logger.info(f"[清理] 已加入延迟删除队列: {len(file_paths)} 个文件，{delay_seconds} 秒后删除")


def process_delete_queue():
    with _delete_lock:
        q = load_delete_queue()
        if not q:
            return
        now = time.time()
        remaining = []
        for item in q:
            path = item.get("path")
            delete_at = item.get("delete_at", 0)
            if now >= delete_at:
                try:
                    # 安全校验：仅删除位于 DOWNLOAD_DIR 内的文件，防止路径穿越
                    abs_path = os.path.abspath(path)
                    abs_dir = os.path.abspath(DOWNLOAD_DIR)
                    if not abs_path.startswith(abs_dir):
                        logger.warning(f"[清理] 跳过非下载目录文件: {abs_path}")
                        continue
                    if os.path.exists(abs_path):
                        os.remove(abs_path)
                        logger.info(f"[清理] 已按策略删除临时文件: {os.path.basename(abs_path)}")
                except Exception as e:
                    logger.warning(f"[清理] 删除文件失败: {path} ({e})")
            else:
                remaining.append(item)
        if len(remaining) != len(q):
            save_delete_queue(remaining)


# ============ 接收者解析 ============
def get_receiver(talker, sender, is_group):
    """
    确定发送目标：
      - 测试模式：统一发到「文件传输助手」
      - 群聊：检查白名单，通过则发群，否则返回 None
      - 私聊：发给 talker
    返回 (receiver_name, can_send, reason)
    """
    if TEST_MODE:
        return "文件传输助手", True, "测试模式"

    if is_group:
        mapping = load_mapping()
        group_name = resolve_display_name(talker, mapping)
        in_wl = (talker in GROUP_WHITELIST) or (group_name in GROUP_WHITELIST)
        if in_wl:
            return group_name, True, "群在白名单内"
        else:
            return group_name, False, f"群 {group_name}({talker}) 不在白名单中"
    else:
        mapping = load_mapping()
        name = resolve_display_name(talker, mapping)
        return name, True, "私聊正常处理"


# ============ 提取链接与指令 ============
def extract_douyin_url(content):
    """从文本中提取抖音链接（兼容既有调用）。"""
    if not content:
        return None
    m = DOUYIN_URL_RE.search(content)
    return m.group(0) if m else None


def extract_media_target(content):
    """统一提取支持的多平台链接、卡片与指令。

    按优先级识别：
      1. 分享卡片（XML appmsg）：提取反转义后完整链接/标题/平台（小红书/B站/网易云/QQ音乐）
      2. 电子书下载指令（./下载 书名）：由 novel_parser 统一处理
      3. 纯文本正则链接：按平台正则顺序匹配

    返回 (platform, target_obj) 或 None：
      - ("douyin", url)
      - ("bilibili", url)
      - ("xhs", url_or_card_dict)
      - ("netease", url_or_card_dict)
      - ("qqmusic", url_or_card_dict)
      - ("novel", book_title)
    """
    if not content:
        return None

    # 分支 1：分享卡片优先识别
    card = detect_card(content)
    if card:
        return (card["platform"], card)

    # 分支 2：电子书指令识别（必须以 Web 配置的触发指令前缀开头）
    book_title = _match_book_command(content)
    if book_title:
        return ("novel", book_title)

    # 分支 3：纯文本正则
    for plat, regex in PLATFORM_URL_RES:
        m = regex.search(content)
        if m:
            return (plat, m.group(0))

    return None


# ============ 解析核心调度 ============
def _download_target(platform, target, raw_content=""):
    """按平台分发解析下载任务。"""
    if platform == "douyin":
        import douyin_parser
        return douyin_parser.resolve_douyin(target)
    elif platform == "bilibili":
        url = target["url"] if isinstance(target, dict) else target
        import bilibili_parser
        return bilibili_parser.resolve_bilibili(url)
    elif platform == "xhs":
        url = target["url"] if isinstance(target, dict) else target
        import xhs_parser
        return xhs_parser.resolve_xhs(url)
    elif platform == "netease":
        import music_parser
        return music_parser.resolve_music(target, "netease", raw_content=raw_content)
    elif platform == "qqmusic":
        import music_parser
        return music_parser.resolve_music(target, "qqmusic", raw_content=raw_content)
    elif platform in ("wikisource", "novel", "ebook"):
        import novel_parser
        return novel_parser.resolve_book(target)
    else:
        raise ValueError(f"未知的解析平台: {platform}")


# ============ wxauto 引用与发送 ============
def _resolve_quote_keyword(target_info, raw_content):
    """确定引用回复的搜索关键词。"""
    if isinstance(target_info, dict):
        title = target_info.get("title")
        if title:
            return title.strip()
    if raw_content:
        first_line = raw_content.strip().splitlines()[0].strip()
        if first_line:
            return first_line[:30]
    return ""


def send_via_wxauto(receiver_name, kind, file_paths, target_info=None, raw_content=None):
    """调用 wxauto 发送解析产物。"""
    from wxauto4 import WeChat
    wx = WeChat()

    # 优先使用 ChatWith 切换会话
    try:
        wx.ChatWith(receiver_name)
        time.sleep(0.3)
    except Exception as e:
        logger.warning(f"[发送] ChatWith({receiver_name}) 失败: {e}")

    # 引用原消息逻辑
    quoted = False
    if QUOTE_REPLY:
        kw = _resolve_quote_keyword(target_info, raw_content)
        if kw:
            try:
                msgs = wx.GetAllMessage()
                target_msg = None
                for m in reversed(msgs[-15:]):
                    c = getattr(m, "content", "") or ""
                    if kw in c:
                        target_msg = m
                        break
                if target_msg and hasattr(target_msg, "Quote"):
                    target_msg.Quote("")
                    quoted = True
                    time.sleep(0.2)
            except Exception as e:
                logger.debug(f"[发送] 引用原消息跳过/未命中: {e}")

    # 执行发送
    for p in file_paths:
        abs_p = os.path.abspath(p)
        if not os.path.exists(abs_p):
            raise FileNotFoundError(f"待发送文件不存在: {abs_p}")
        wx.SendFiles(abs_p)
        time.sleep(0.5)

    return True


# ============ 任务分发与执行 ============
def process_message_event(evt):
    """处理单条微信消息事件。"""
    rawid = evt.get("rawid")
    if rawid and is_processed(rawid):
        return

    content = evt.get("content") or ""
    parsed = extract_media_target(content)
    if not parsed:
        if rawid:
            mark_processed(rawid)
        return

    platform, target = parsed
    plat_name = PLATFORM_NAMES.get(platform, platform)

    if not _platform_enabled(platform):
        logger.info(f"[{plat_name}] 平台功能已关闭，跳过处理")
        if rawid:
            mark_processed(rawid)
        return

    talker = evt.get("talker") or ""
    sender = evt.get("sender") or ""
    is_group = bool(evt.get("is_group") or (talker and talker.endswith("@chatroom")))

    receiver_name, can_send, reason = get_receiver(talker, sender, is_group)
    if not can_send:
        logger.info(f"[{plat_name}] 跳过发送: {reason}")
        if rawid:
            mark_processed(rawid)
        return

    logger.info(f"[{plat_name}] 收到请求，目标接收者: {receiver_name}")
    t0 = time.time()
    task_id = tasks.add_task(
        platform=plat_name,
        receiver=receiver_name,
        target=str(target.get("title") if isinstance(target, dict) else target)
    )

    try:
        kind, files = _download_target(platform, target, raw_content=content)
        send_via_wxauto(receiver_name, kind, files, target_info=target, raw_content=content)
        schedule_deletion(files, DELETE_AFTER_SECONDS)
        tasks.update_task(task_id, status="success", duration=time.time() - t0)
        logger.info(f"[{plat_name}] 发送成功！耗时: {time.time() - t0:.1f}s")
    except Exception as e:
        tasks.update_task(task_id, status="failed", error=str(e), duration=time.time() - t0)
        logger.error(f"[{plat_name}] 处理失败: {e}")
    finally:
        if rawid:
            mark_processed(rawid)


# ============ 监听 Worker ============
_worker_stop_event = threading.Event()
_worker_thread = None


def _listener_loop():
    logger.info("[监听] Worker 线程启动")
    state.set_listener_running(True)

    while not _worker_stop_event.is_set():
        try:
            _apply_config()
            process_delete_queue()
            flush_processed_if_needed()
            time.sleep(1)
        except Exception as e:
            logger.error(f"[监听] Worker 异常: {e}")
            time.sleep(2)

    state.set_listener_running(False)
    logger.info("[监听] Worker 线程已停止")


def start_listener():
    global _worker_thread
    if _worker_thread and _worker_thread.is_alive():
        return True
    _worker_stop_event.clear()
    _worker_thread = threading.Thread(target=_listener_loop, daemon=True, name="MainListenerWorker")
    _worker_thread.start()
    return True


def stop_listener():
    _worker_stop_event.set()
    if _worker_thread and _worker_thread.is_alive():
        _worker_thread.join(timeout=3)
    return True


def is_listener_running():
    return _worker_thread is not None and _worker_thread.is_alive()
