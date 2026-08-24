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


# 去重集合的线程安全访问（推送线程与轮询主循环会并发读写）
_processed_lock = threading.Lock()


def _is_processed(processed, key):
    """判断某 rawid 是否已处理（线程安全）。"""
    if not key:
        return False
    with _processed_lock:
        return key in processed


def _mark_processed(processed, key):
    """原子地标记去重并持久化；返回 False 表示该消息已处理过（应跳过）。"""
    if not key:
        return True
    with _processed_lock:
        if key in processed:
            return False
        processed.add(key)
        save_processed(processed)
        return True


# ============ 1. 会话类型判断（红线策略）============
def _classify(wxid):
    if wxid == "filehelper":
        return "filehelper"
    if wxid.endswith("@chatroom"):
        return "group"
    if wxid.endswith("@openim"):
        return "openim"
    if wxid.startswith("wxid_"):
        return "private"
    return "other"


# ============ 2. WeFlow 主动推送（SSE）监听与链接识别 ============
def _sse_events(resp, stop_event=None, should_stop=None):
    """从 urllib 的 HTTPResponse 逐事件解析 SSE，yield (event_name, data_payload)。

    读超时（SSE_READ_TIMEOUT）须大于 WeFlow 心跳间隔（实测约 25s），正常由心跳保活、
    不会触发；仅当连接失活（无心跳且未断开）时才超时抛异常，由上层 _push_loop 重连。
    stop_event / should_stop 在每读到一行（心跳）后检查，用于停止监听或关闭推送开关。
    """
    event_name = None
    data_lines = []
    while True:
        if should_stop is not None and should_stop():
            return
        if stop_event is not None and stop_event.is_set():
            return
        raw = resp.readline()
        if not raw:
            break  # EOF：连接被服务端关闭
        line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
        if line == "":
            if data_lines:
                yield event_name or "message", "\n".join(data_lines)
            event_name = None
            data_lines = []
        elif line.startswith(":"):
            continue  # 注释/心跳（: ping）
        elif line.startswith("event:"):
            event_name = line[len("event:"):].strip()
        elif line.startswith("data:"):
            data_lines.append(line[len("data:"):].strip())
    if data_lines:
        yield event_name or "message", "\n".join(data_lines)


def _process_link(target, display_name, url, platform, rawid, processed, quote_key=None):
    """对一条命中的链接消息执行解析+发送，并持久化去重。"""
    # 先原子标记去重，避免解析/发送抛异常时同一条消息被重复处理（推送/轮询并发也安全）
    if not _mark_processed(processed, rawid):
        return

    # ./下载 命令分支（维基文库公有资源）：url 此处承载书名文本
    if platform == "wikisource":
        _process_command(target, display_name, url, rawid, processed, quote_key)
        return

    pname = PLATFORM_NAMES.get(platform, platform)
    task = tasks.add_task(display_name, url, status="processing")
    logger.info(f"[命中] {display_name}({target}) 发来{pname}链接: {url}")

    if not _platform_enabled(platform):
        logger.info(f"[跳过] {pname}平台已关闭，忽略该链接")
        tasks.update_task(task["id"], status="failed", error=f"{pname}平台已关闭")
        return

    try:
        kind, file_paths = resolve_link(url, platform)
    except Exception as e:
        logger.error(f"[解析][{pname}] {e} —— 已标记避免重复，跳过")
        tasks.update_task(task["id"], status="failed", error=str(e)[:200])
        return

    quote_url = url if QUOTE_REPLY else None
    sent = send_files(display_name, file_paths, target, quote_url, quote_key)
    if sent:
        for p in file_paths:
            schedule_delete(p)
        if kind == "note":
            label = "图文"
        elif kind == "audio":
            label = "音频"
        else:
            label = "视频"
        tasks.update_task(task["id"], status="success",
                          video=f"[{pname}] {label} {len(file_paths)} 个文件")
    else:
        tasks.update_task(task["id"], status="failed", error="发送失败")


# ============ 链接处理队列（解析+发送在独立线程串行执行，避免阻塞主循环/推送线程）============
_pending_links = queue.Queue()


def _enqueue_link(target, display_name, url, platform, rawid, quote_key=None):
    """把一条命中的链接放入处理队列，由后台线程串行解析+发送。

    quote_key 用于发送时引用原消息：普通链接为 None（用 URL 匹配）；
    卡片为标题文本（wxauto4 GetAllMessage 返回的卡片 content 不含 URL，只能用标题匹配）。
    """
    _pending_links.put((target, display_name, url, platform, rawid, quote_key))


def _process_worker(processed, stop_event):
    """单线程串行处理队列中的链接（解析+发送），避免阻塞主循环与推送线程。

    发送操作（wxauto4 切窗/引用/发文件）单条可耗时数十秒，若放在主循环里会阻塞
    「停止监听」的响应；放独立线程后，主循环/推送线程只负责扫描并入队，停止即时生效。
    """
    while stop_event is None or not stop_event.is_set():
        try:
            item = _pending_links.get(timeout=1)
        except queue.Empty:
            continue
        target, display_name, url, platform, rawid, quote_key = item
        try:
            _process_link(target, display_name, url, platform, rawid, processed, quote_key)
        except Exception:
            logger.error("处理链接异常:\n" + traceback.format_exc())
    logger.info("[处理] 链接处理线程已退出")


def _resolve_target(session_type, session_id, group_name="", source_name=""):
    """红线策略：根据会话类型 + 白名单 + 测试模式确定发送目标。

    返回 (target_wxid, display_name) 或 None（表示跳过）。
    """
    if session_type == "group":
        if session_id not in GROUP_WHITELIST and group_name not in GROUP_WHITELIST:
            return None
        target = session_id
        display_name = resolve_display_name(session_id)
        if display_name == session_id:          # 映射未命中，用群名兜底
            display_name = group_name or session_id
    elif session_type == "private":
        target = session_id
        display_name = resolve_display_name(session_id)
        if display_name == session_id:          # 映射未命中，用发送者名兜底
            display_name = source_name or session_id
    else:
        return None  # filehelper / openim / 其它：忽略

    if TEST_MODE:
        return "filehelper", "文件传输助手"
    return target, display_name


def _handle_push_event(data, processed):
    """处理一条 WeFlow 推送事件：只处理 message.new，识别链接并走解析发送。"""
    if data.get("event") != "message.new":
        return  # 忽略 ready / message.revoke 等其它事件

    session_id = data.get("sessionId") or ""
    content = data.get("content") or ""
    rawid = str(data.get("rawid") or data.get("messageKey") or "")

    if not session_id:
        return
    if _is_processed(processed, rawid):
        return

    session_type = data.get("sessionType") or _classify(session_id)
    resolved = _resolve_target(session_type, session_id,
                               data.get("groupName") or "", data.get("sourceName") or "")
    if resolved is None:
        return
    target, display_name = resolved

    # 分享卡片（XML appmsg）：优先从卡片 <url> 取完整反转义链接（避开文本正则截断）
    card = detect_card(content)
    if card:
        _enqueue_link(target, display_name, card["url"], card["platform"], rawid, card.get("title"))
        return

    # 命令：电子书下载（支持自定义前缀或默认 ./下载 书名）
    book_title = _match_book_command(content)
    if book_title:
        _enqueue_link(target, display_name, book_title, "wikisource", rawid)
        return

    for platform, regex in PLATFORM_URL_RES:
        m = regex.search(content)
        if m:
            _enqueue_link(target, display_name, m.group(0), platform, rawid)
            return


def _scan_messages(processed, label="扫描"):
    """扫描活跃会话的最近消息，识别未处理链接并处理（启动补扫 / 轮询兜底共用）。

    用 serverId 作为去重键（与 SSE 推送的 rawid 一致），与推送共享同一去重集合；
    同时兼顾旧版 localId 键，避免跨版本重复处理。轮询能覆盖推送漏掉的消息
    （例如「自己发送」的消息，SSE 不会推给自己）。
    """
    s = _get("/api/v1/sessions", {"limit": 1000})
    if "error" in s:
        state.set_status("weflow", "error", f"WeFlow 不可达: {s['error']}")
        logger.warning(f"[{label}] WeFlow 不可达: {s['error']}")
        return
    state.set_status("weflow", "ok", "WeFlow 连接正常")

    now = int(time.time())
    found = []

    for item in s.get("sessions", []):
        talker = item.get("username", "")
        ts = item.get("lastTimestamp") or 0
        if now - ts > ACTIVE_WINDOW:
            continue

        resolved = _resolve_target(_classify(talker), talker, item.get("displayName") or "", "")
        if resolved is None:
            continue
        target, display_name = resolved

        r = _get("/api/v1/messages", {"talker": talker, "limit": LOOKBACK_LIMIT})
        if "error" in r:
            continue

        for msg in r.get("messages", []):
            server_id = str(msg.get("serverId") or "")
            local_id = str(msg.get("localId") or "")
            # 去重：推送 rawid == serverId；同时兼顾旧版 localId 键
            if _is_processed(processed, server_id) or _is_processed(processed, local_id):
                continue
            key = server_id or local_id
            if not key:
                continue
            content = msg.get("content") or ""
            # 分享卡片（XML appmsg）：优先从卡片 <url> 取完整反转义链接（避开文本正则截断）
            card = detect_card(content)
            if card:
                found.append((target, display_name, card["url"], card["platform"], key, card.get("title")))
                continue
            # 命令：电子书下载（支持自定义前缀或默认 ./下载 书名）
            book_title = _match_book_command(content)
            if book_title:
                found.append((target, display_name, book_title, "wikisource", key, None))
                continue
            for platform, regex in PLATFORM_URL_RES:
                m = regex.search(content)
                if m:
                    found.append((target, display_name, m.group(0), platform, key, None))
                    break

    if found:
        logger.info(f"[{label}] 发现 {len(found)} 条新链接，已加入处理队列")
    for target, display_name, url, platform, key, quote_key in found:
        _enqueue_link(target, display_name, url, platform, key, quote_key)


def _listen_sse(processed, stop_event=None, should_stop=None):
    """订阅 WeFlow SSE 推送，阻塞处理消息事件，直到连接断开或收到停止信号。"""
    url = _base_url() + "/api/v1/push/messages"
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {_token()}",
        "Accept": "text/event-stream",
        "Cache-Control": "no-cache",
    })
    # 读超时设为 SSE_READ_TIMEOUT（> 心跳 25s）：正常由心跳保活，超时仅用于探测连接失活
    resp = urllib.request.urlopen(req, timeout=SSE_READ_TIMEOUT)
    try:
        ct = (resp.headers.get("Content-Type") or "").lower()
        if "text/event-stream" not in ct:
            body = ""
            try:
                body = resp.read(256).decode("utf-8", errors="replace").strip()
            except Exception:
                pass
            state.set_status("weflow", "error", body or "推送不可用")
            raise RuntimeError(body or "WeFlow 主动推送不可用（响应非 event-stream）")
        state.set_status("weflow", "ok", "WeFlow 推送已连接")
        logger.info("[推送] 已订阅 WeFlow 消息推送（SSE）")
        for evt_name, payload in _sse_events(resp, stop_event, should_stop):
            if evt_name != "message.new":
                continue
            try:
                data = json.loads(payload)
            except Exception:
                continue
            _handle_push_event(data, processed)
    finally:
        try:
            resp.close()
        except Exception:
            pass


def _push_enabled():
    """读取配置中主动推送开关（默认 True）。"""
    try:
        return bool(get_config().get("advanced", {}).get("listen_push", True))
    except Exception:
        return True


def _push_loop(processed, stop_event):
    """独立线程：订阅 WeFlow SSE 推送，断线自动重连，直至收到停止信号。"""
    reconnect_delay = 3.0
    while stop_event is None or not stop_event.is_set():
        # 开关被关闭时：短暂等待后重新检查（可能在运行中被重新打开）
        if not _push_enabled():
            if stop_event is not None:
                stop_event.wait(3)
            else:
                time.sleep(3)
            continue
        try:
            _listen_sse(processed, stop_event,
                        should_stop=lambda: (stop_event is not None and stop_event.is_set())
                                            or not _push_enabled())
            reconnect_delay = 3.0   # 正常断开则重置退避
        except Exception as e:
            if stop_event is not None and stop_event.is_set():
                break
            state.set_status("weflow", "error", f"推送连接中断: {str(e)[:120]}")
            logger.warning(f"[推送] 连接中断：{e}；{reconnect_delay:.0f}s 后重连")
            reconnect_delay = min(reconnect_delay * 2, 30.0)
        if stop_event is not None:
            stop_event.wait(reconnect_delay)
        else:
            time.sleep(reconnect_delay)
    logger.info("[推送] 推送线程已退出")


# ============ 3. 解析视频 ============
def resolve_douyin(url):
    """返回 (kind, file_paths)：kind 为 "video"/"note"，file_paths 为本地文件路径列表。

    PARSE_MODE="real" 时调用 douyin_parser 统一入口（视频/图文都支持）。
    """
    if PARSE_MODE == "fake":
        fake = os.path.join(BASE_DIR, "测试视频_请忽略.mp4")
        if not os.path.exists(fake):
            raise FileNotFoundError(f"测试视频不存在: {fake}")
        return "video", [fake]
    import douyin_parser
    return douyin_parser.resolve_douyin(url)


def resolve_link(url, platform):
    """多平台统一分发入口：按 platform 调用对应解析器，返回 (kind, file_paths)。"""
    if platform == "douyin":
        return resolve_douyin(url)
    if platform == "bilibili":
        import bilibili_parser
        return bilibili_parser.resolve_bilibili(url)
    if platform == "xhs":
        import xhs_parser
        return xhs_parser.resolve_xhs(url)
    if platform == "netease":
        import music_parser
        return music_parser.resolve_music(url, "netease")
    if platform == "qqmusic":
        import music_parser
        return music_parser.resolve_music(url, "qqmusic")
    raise RuntimeError(f"未知平台: {platform}")


# ============ 4. 发送视频（发对人是红线）============
def _attach_desktop():
    """在后台/服务环境下确保附加到当前活动用户的交互桌面 (WinSta0\\Default)。"""
    try:
        import win32service, win32con
        hwinsta = win32service.OpenWindowStation('WinSta0', False, win32con.MAXIMUM_ALLOWED)
        hwinsta.SetProcessWindowStation()
        hdesk = win32service.OpenDesktop('Default', 0, False, win32con.MAXIMUM_ALLOWED)
        hdesk.SetThreadDesktop()
    except Exception:
        pass


def _find_wechat_hwnd():
    """找到微信主窗口句柄（Qt51514QWindowIcon，优先标题含「微信」）。"""
    _attach_desktop()
    import psutil
    pids = {p.info['pid'] for p in psutil.process_iter(['pid', 'name'])
            if p.info['name'] == 'Weixin.exe'}
    if not pids:
        return None

    targets = []
    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int, ctypes.c_int)

    def cb(hwnd, _):
        try:
            pid = ctypes.c_ulong()
            ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value in pids:
                buf_cls = ctypes.create_unicode_buffer(256)
                ctypes.windll.user32.GetClassNameW(hwnd, buf_cls, 256)
                cls = buf_cls.value
                if cls == 'Qt51514QWindowIcon' or 'Qt' in cls or cls == 'WeChatMainWndForPC':
                    buf_title = ctypes.create_unicode_buffer(256)
                    ctypes.windll.user32.GetWindowTextW(hwnd, buf_title, 256)
                    title = buf_title.value
                    targets.append((hwnd, cls, title))
        except Exception:
            pass
        return True

    try:
        ctypes.windll.user32.EnumWindows(WNDENUMPROC(cb), 0)
    except Exception:
        pass

    for h, cls, title in targets:
        if '微信' in title:
            return h
    return targets[0][0] if targets else None


def _maximize_wechat():
    """发送前把微信主窗口恢复并最大化，返回是否成功。"""
    hwnd = _find_wechat_hwnd()
    if not hwnd:
        logger.info("[窗口] 未找到微信主窗口，跳过最大化")
        return False
    try:
        ctypes.windll.user32.ShowWindow(hwnd, 9)       # SW_RESTORE
        ctypes.windll.user32.SetForegroundWindow(hwnd)
        time.sleep(0.2)
        ctypes.windll.user32.ShowWindow(hwnd, 3)       # SW_MAXIMIZE
        time.sleep(0.3)
        return True
    except Exception as e:
        logger.warning(f"[窗口] 最大化异常: {e}")
        return False


def _minimize_wechat():
    """发送完成后最小化微信，返回是否成功。"""
    hwnd = _find_wechat_hwnd()
    if not hwnd:
        logger.info("[窗口] 未找到微信主窗口，跳过最小化")
        return False
    try:
        ctypes.windll.user32.ShowWindow(hwnd, 6)       # SW_MINIMIZE（对任意状态窗口均有效）
        time.sleep(0.3)
        return True
    except Exception as e:
        logger.warning(f"[窗口] 最小化异常: {e}")
        return False


def _dblclick_wechat_tab():
    """双击左侧导航栏「微信」标签，切回聊天列表主界面，返回是否成功。"""
    from wxauto4.uia import uiautomation as auto
    hwnd = _find_wechat_hwnd()
    if not hwnd:
        logger.info("[切换] 未找到微信主窗口")
        return False
    try:
        ctypes.windll.user32.SetForegroundWindow(hwnd)
    except Exception:
        pass
    time.sleep(0.2)
    try:
        root = auto.ControlFromHandle(hwnd)
        btn = root.ButtonControl(searchDepth=0xFFFFFFFF, Name='微信')
        if not btn.Exists(2):
            logger.info("[切换] 未找到「微信」标签按钮")
            return False
        btn.DoubleClick()
    except Exception as e:
        logger.warning(f"[切换] 双击微信标签异常: {e}")
        return False
    time.sleep(0.5)
    return True


def switch_chat(wx, display_name, max_retry=3):
    """切换到目标会话：每次先双击微信导航栏最上面的「微信」标签切回主界面，再 ChatWith 命中目标好友。"""
    for attempt in range(max_retry):
        _dblclick_wechat_tab()

        try:
            wx.ChatWith(display_name, exact=True)
        except Exception as e:
            logger.warning(f"[切换] 第 {attempt + 1} 次 ChatWith 异常: {e}")

        try:
            info = wx.ChatInfo() or {}
            if info.get("chat_name") == display_name:
                return True
        except Exception as e:
            logger.warning(f"[切换] 校验异常: {e}")

        time.sleep(0.3)
    return False


def _quote_key(url):
    """从抖音链接提取用于匹配的关键词（短链路径或 video/note id）。"""
    m = re.search(r"v\.douyin\.com/([\w\-]+)", url)
    if m:
        return f"v.douyin.com/{m.group(1)}"
    m = re.search(r"douyin\.com/((?:video|note)/\d+)", url)
    if m:
        return f"douyin.com/{m.group(1)}"
    return url


def _quote_message(wx, url, quote_key=None):
    """在目标会话里定位那条链接消息并右键引用。返回是否成功。

    quote_key 用于卡片消息：wxauto4 GetAllMessage 返回的卡片 content 是渲染后的
    标题文本（type='link' 等），不含原始 URL，因此卡片改用标题(quote_key)匹配，
    并放宽类型白名单接受 link/app/card 类消息。普通文本链接 quote_key 为 None，
    仍用原有 URL 子串匹配。
    """
    try:
        msgs = wx.GetAllMessage()
    except Exception:
        return False
    key = _quote_key(url)
    # 允许的类型：文本/其它（原有）+ 卡片/链接类（appmsg 分享，type='link' 等）
    accept_types = ("text", "other", "link", "app", "card")
    # 链接消息通常是会话里最新的一条，从后往前找更快命中
    for m in reversed(msgs):
        t = getattr(m, "type", None)
        if t not in accept_types:
            continue
        content = getattr(m, "content", "") or ""
        # 卡片：用标题(quote_key)匹配（content 不含 URL）
        if quote_key and t in ("link", "app", "card") and quote_key in content:
            try:
                m.right_click()
                time.sleep(0.15)
                m.select_option("引用")
                time.sleep(0.15)
                return True
            except Exception:
                return False
        # 文本链接：原有 URL 子串匹配
        if t in ("text", "other") and (key in content or url in content):
            try:
                m.right_click()
                time.sleep(0.15)
                m.select_option("引用")
                time.sleep(0.15)
                return True
            except Exception:
                return False
    return False


# 微信实例缓存：复用连接，避免每次发送都重新实例化（约省 1s/次）。
# worker 单线程调用，无需加锁；失效时由调用方捕获异常后重建。
_wx_cache = None


def _get_wechat():
    global _wx_cache
    if _wx_cache is None:
        from wxauto4 import WeChat
        _wx_cache = WeChat(ads=False, resize=False)
    return _wx_cache


def _reset_wechat():
    global _wx_cache
    _wx_cache = None


def send_files(display_name, file_paths, target_wxid, quote_url=None, quote_key=None):
    """用 wxauto4 发送文件（视频或图文图片）给指定会话。

    先可靠切换到目标会话；若 quote_url 非空，先定位对方发来的那条链接消息并
    右键引用，再发送文件，使视频/图文附着在引用块下方。
    """
    _maximize_wechat()

    wx = _get_wechat()

    ok = switch_chat(wx, display_name)
    if not ok:
        # 可能是缓存的实例失效（如微信重启），重建连接后再试一次
        _reset_wechat()
        wx = _get_wechat()
        ok = switch_chat(wx, display_name)
    if not ok:
        logger.warning(f"[发送] 警告：无法切换到 {display_name!r}，已中止（避免发错人）")
        return False

    for p in file_paths:
        if not os.path.exists(p):
            logger.error(f"[发送] 文件不存在: {p}")
            return False

    if quote_url:
        try:
            if _quote_message(wx, quote_url, quote_key):
                logger.info(f"[引用] 已引用原链接消息: {quote_url}")
            else:
                logger.warning(f"[引用] 未定位到原链接消息，改为直接发送: {quote_url}")
        except Exception as e:
            logger.warning(f"[引用] 引用失败，改为直接发送: {e}")

    # 已通过 switch_chat 切换到目标会话，此处不传 who，直接发给当前会话，
    # 避免 SendFiles 内部再次搜索切换（省一次定位开销）。
    r = wx.SendFiles(file_paths)
    names = "、".join(os.path.basename(p) for p in file_paths)
    logger.info(f"[发送] 已发送 {len(file_paths)} 个文件({names}) -> {display_name} (wxid={target_wxid}) 返回={r}")

    _minimize_wechat()
    return True


# ============ ./下载 命令处理（维基文库公有资源）============
def send_text(display_name, text, target_wxid):
    """发送纯文本消息（./下载 未命中时回复提示）。"""
    _maximize_wechat()
    wx = _get_wechat()
    ok = switch_chat(wx, display_name)
    if not ok:
        _reset_wechat()
        wx = _get_wechat()
        ok = switch_chat(wx, display_name)
    if not ok:
        logger.warning(f"[发送] 无法切换到 {display_name!r}，已中止文本发送（避免发错人）")
        return False
    try:
        wx.SendMsg(text)
        logger.info(f"[发送] 已发送文本 -> {display_name} (wxid={target_wxid}): {text[:30]}")
    except Exception as e:
        logger.warning(f"[发送] 文本发送失败: {e}")
        return False
    finally:
        _minimize_wechat()
    return True


def _process_command(target, display_name, title, rawid, processed, quote_key=None):
    """处理电子书下载命令（中文电子书与网络文学极速全本检索下载）。"""
    import novel_parser
    task = tasks.add_task(display_name, f"电子书: 《{title}》", status="processing")
    logger.info(f"[电子书] {display_name}({target}) 请求下载: 《{title}》")

    if not _platform_enabled("ebook"):
        logger.info(f"[跳过] 电子书下载功能已关闭，忽略《{title}》")
        tasks.update_task(task["id"], status="failed", error="电子书下载功能已关闭")
        return

    cfg = get_config()
    dl_dir = (cfg.get("ebook", {}) or {}).get("download_dir") or DOWNLOAD_DIR
    try:
        import ebook_engine
        kind, file_paths = ebook_engine.resolve_book(title, dl_dir, prefer_format="epub")
    except Exception as e:
        # 兼容自定义或标准未找到异常
        if "未找到" in str(e) or e.__class__.__name__ == "BookNotFound":
            logger.info(f"[电子书] 未找到「{title}」: {e}")
            send_text(display_name, f"未找到《{title}》相关电子书资源", target)
            tasks.update_task(task["id"], status="success", video="未找到（已回复提示）")
            return
        logger.error(f"[电子书] 处理「{title}」异常: {e}")
        send_text(display_name, f"未找到《{title}》相关电子书资源", target)
        tasks.update_task(task["id"], status="failed", error=str(e)[:200])
        return

    sent = send_files(display_name, file_paths, target, None, quote_key)
    if sent:
        for p in file_paths:
            schedule_delete(p)  # 复用延迟删除（默认 180s）
        ext = os.path.splitext(file_paths[0])[1].upper().lstrip(".")
        tasks.update_task(task["id"], status="success",
                          video=f"[电子书] 《{title}》全本 ({ext})")
    else:
        tasks.update_task(task["id"], status="failed", error="发送失败")


# ============ 5. 发送后延迟清理（非阻塞，线程安全）============
_pending_deletions = {}
_pending_lock = threading.Lock()


def load_delete_queue():
    """启动时加载上次未完成的待删除队列。"""
    if not os.path.exists(DELETE_QUEUE_FILE):
        return {}
    try:
        with open(DELETE_QUEUE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return {k: v for k, v in data.items()} if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_delete_queue():
    with _pending_lock:
        data = dict(_pending_deletions)
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(DELETE_QUEUE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def schedule_delete(video_path):
    """发送后把视频加入延迟删除队列。"""
    if not DELETE_AFTER_SECONDS or DELETE_AFTER_SECONDS <= 0:
        return
    real = os.path.realpath(video_path)
    with _pending_lock:
        _pending_deletions[real] = time.time() + DELETE_AFTER_SECONDS
    save_delete_queue()
    logger.info(f"[清理] 已排程：{os.path.basename(video_path)} 将在 {DELETE_AFTER_SECONDS}s 后自动删除")


def process_deletions():
    """删除已到期的视频（文件删除在锁外执行）。"""
    now = time.time()
    expired = []
    with _pending_lock:
        for real in list(_pending_deletions):
            if now >= _pending_deletions[real]:
                expired.append(real)
                _pending_deletions.pop(real, None)
    for real in expired:
        cleanup_video(real)
    if expired:
        save_delete_queue()


def cleanup_video(video_path):
    """删除已下载的视频/图片（仅限各平台下载目录内，防止误删）。"""
    try:
        real = os.path.realpath(video_path)
        allowed = {os.path.realpath(d) for d in _delete_allowed_dirs()}
        if not any(real == base or real.startswith(base + os.sep) for base in allowed):
            logger.info(f"[清理] 跳过：非下载目录文件 {video_path}")
            return
        if not os.path.isfile(real):
            return
        os.remove(real)
        logger.info(f"[清理] 已删除文件: {os.path.basename(video_path)}")
    except Exception as e:
        logger.warning(f"[清理] 删除失败 {video_path}: {e}")


def _delete_allowed_dirs():
    """返回所有平台配置的下载目录（用于清理时的安全范围判断）。"""
    dirs = [DOWNLOAD_DIR]
    try:
        cfg = get_config()
        for sec in ("douyin", "bilibili", "xhs"):
            d = cfg.get(sec, {}).get("download_dir")
            if d:
                dirs.append(d)
    except Exception:
        pass
    return [d for d in dirs if d]


# ============ 连接测试 ============
def probe_wechat_status():
    """轻量探测微信运行状态（只查进程+窗口，不连接 UIA），更新 state。"""
    try:
        hwnd = _find_wechat_hwnd()
        if hwnd:
            state.set_status("wechat", "ok", "微信运行中")
        else:
            state.set_status("wechat", "error", "微信未运行：未找到微信主窗口")
    except Exception as e:
        state.set_status("wechat", "error", f"探测失败: {str(e)[:120]}")


def test_wechat():
    """测试微信：检查进程 + 窗口 + wxauto4 连接。返回 (ok, detail)。"""
    try:
        hwnd = _find_wechat_hwnd()
        if not hwnd:
            return False, "微信未运行：未找到微信主窗口，请先启动并登录微信"
        from wxauto4 import WeChat
        WeChat(ads=False, resize=False)
        _minimize_wechat()   # 测试完成后最小化微信窗口，避免停留在桌面
        return True, "微信已连接"
    except Exception as e:
        return False, f"微信连接失败: {str(e)[:160]}"


def _probe_push():
    """探测 WeFlow 主动推送（SSE）是否可用。返回 (ok, detail)。"""
    url = _base_url() + "/api/v1/push/messages"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {_token()}"})
    try:
        resp = urllib.request.urlopen(req, timeout=3)
    except Exception as e:
        return False, f"无法连接推送: {str(e)[:120]}"
    try:
        ct = (resp.headers.get("Content-Type") or "").lower()
        if "text/event-stream" in ct:
            return True, "主动推送已开启"
        body = resp.read(256).decode("utf-8", errors="replace").strip()
        return False, body or "推送不可用"
    finally:
        try:
            resp.close()
        except Exception:
            pass


def test_weflow():
    """测试 WeFlow 连接；若启用了主动推送则顺带探测推送。返回 (ok, detail)。"""
    try:
        from mapping import test_connection
        ok, detail = test_connection()
    except Exception as e:
        return False, f"WeFlow 测试异常: {str(e)[:160]}"
    if not ok:
        return False, detail
    if _push_enabled():
        push_ok, push_detail = _probe_push()
        if not push_ok:
            return False, f"WeFlow 已连接，但主动推送不可用：{push_detail}（请在 WeFlow 设置→API 服务 中开启「主动推送」，或在高级设置改用轮询监听）"
        return True, "WeFlow 连接成功，主动推送已开启"
    return True, "WeFlow 连接成功（当前为轮询监听，无需主动推送）"


def test_douyin():
    """测试抖音解析。返回 (ok, detail)。"""
    try:
        import douyin_parser
    except Exception as e:
        return False, f"抖音解析模块加载失败: {str(e)[:160]}"
    try:
        return douyin_parser.test_douyin()
    except Exception as e:
        return False, f"抖音解析测试异常: {str(e)[:160]}"


def test_bilibili():
    """测试 B站解析环境。返回 (ok, detail)。"""
    try:
        import bilibili_parser
    except Exception as e:
        return False, f"B站解析模块加载失败: {str(e)[:160]}"
    try:
        return bilibili_parser.test_bilibili()
    except Exception as e:
        return False, f"B站解析测试异常: {str(e)[:160]}"


def test_xhs():
    """测试小红书解析环境。返回 (ok, detail)。"""
    try:
        import xhs_parser
    except Exception as e:
        return False, f"小红书解析模块加载失败: {str(e)[:160]}"
    try:
        return xhs_parser.test_xhs()
    except Exception as e:
        return False, f"小红书解析测试异常: {str(e)[:160]}"


# ============ 后台 worker（可停止的监听循环：推送线程 + 轮询主循环）============
def run_worker(stop_event=None):
    """后台监听：主动推送（SSE，独立线程）+ 轮询兜底（主循环）。

    - 主动推送线程负责实时处理（收不到自己发送的消息）。
    - 主循环按 poll_interval 轮询扫描，覆盖推送漏掉的消息（含自己发送的）。
    - 两者共用同一 rawid 去重集合，不会重复处理。
    stop_event 非空时可通过 set() 请求停止，主循环与推送线程均能快速退出。
    """
    _apply_config()
    mapping = load_mapping()
    processed = load_processed()

    with _pending_lock:
        _pending_deletions.update(load_delete_queue())
    mode = ("推送+轮询" if (LISTEN_PUSH and LISTEN_POLL)
            else "仅推送" if LISTEN_PUSH
            else "仅轮询" if LISTEN_POLL
            else "无（推送/轮询均已关闭）")
    logger.info(f"[启动] 映射 {len(mapping)} 条 | 解析模式={PARSE_MODE} | "
                f"测试模式={'开(发文件传输助手)' if TEST_MODE else '关(发真实接收者)'} | "
                f"群白名单 {len(GROUP_WHITELIST)} 个")
    logger.info(f"[启动] 已处理消息 {len(processed)} 条 | 待删除队列 {len(_pending_deletions)} 个 | "
                f"发送后延迟删除 {DELETE_AFTER_SECONDS}s | 监听方式={mode} | 轮询间隔 {POLL_INTERVAL}s")
    process_deletions()
    probe_wechat_status()

    # 链接处理线程：串行解析+发送（放在补扫/推送之前，保证入队的链接都能被处理）
    proc_thread = threading.Thread(target=_process_worker, args=(processed, stop_event),
                                   name="link-processor", daemon=True)
    proc_thread.start()

    # 启动时一次性补扫：处理监听停止期间错过的新链接
    try:
        _scan_messages(processed, label="补扫")
    except Exception as e:
        logger.warning(f"[补扫] 补扫异常（忽略，继续）: {e}")

    # 主动推送线程（可选）
    push_thread = None
    if LISTEN_PUSH:
        push_thread = threading.Thread(target=_push_loop, args=(processed, stop_event),
                                       name="sse-push", daemon=True)
        push_thread.start()

    # 主循环：轮询扫描 + 配置刷新 + 延迟删除 + 微信状态
    while stop_event is None or not stop_event.is_set():
        try:
            _apply_config()          # 每轮刷新配置（开关/间隔热更新）
            process_deletions()
            probe_wechat_status()
            if LISTEN_POLL:
                _scan_messages(processed, label="轮询")
        except Exception:
            logger.error("运行异常:\n" + traceback.format_exc())
        if stop_event is not None:
            stop_event.wait(POLL_INTERVAL)
        else:
            time.sleep(POLL_INTERVAL)

    logger.info("[退出] 监听已停止")


if __name__ == "__main__":
    # 兼容：直接 python main.py 仍可运行（Ctrl+C 停止）
    try:
        run_worker(None)
    except KeyboardInterrupt:
        logger.info("\n[退出] 已停止")



