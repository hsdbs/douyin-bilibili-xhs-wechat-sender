# -*- coding: utf-8 -*-
"""
统一配置管理模块。

- 配置文件：config/config.json（JSON，UTF-8）
- 首次运行自动创建默认配置，并从旧数据自动迁移（根目录 JSON 数据文件）
- 敏感字段（WeFlow Token）在 API 输出时脱敏，不写入普通日志
- 线程安全（RLock）
"""
import copy
import json
import os
import sys
import threading

# ============ 目录 ============
# 打包（PyInstaller frozen）时：可写数据（config/data/logs/videos）放在 exe 同级目录，
# 只读静态资源从 _internal（sys._MEIPASS）读取。
if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(os.path.abspath(sys.executable))
    STATIC_DIR = os.path.join(getattr(sys, "_MEIPASS", BASE_DIR), "web", "static")
else:
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # 项目根目录
    STATIC_DIR = os.path.join(BASE_DIR, "web", "static")

CONFIG_DIR = os.path.join(BASE_DIR, "config")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")
DATA_DIR = os.path.join(BASE_DIR, "data")
LOG_DIR = os.path.join(BASE_DIR, "logs")
VIDEO_DIR = os.path.join(BASE_DIR, "videos")

# 旧数据文件（迁移用）
LEGACY_DATA_FILES = {
    "processed_rawids.json": os.path.join(BASE_DIR, "processed_rawids.json"),
    "processed_msgs.json": os.path.join(BASE_DIR, "processed_msgs.json"),
    "pending_deletions.json": os.path.join(BASE_DIR, "pending_deletions.json"),
    "wxid_displayname_mapping.json": os.path.join(BASE_DIR, "wxid_displayname_mapping.json"),
}

# 敏感字段
SENSITIVE_KEYS = ("token",)
MASK = "******"


# ============ 默认配置 ============
def _default_config():
    return {
        "version": 1,
        "weflow": {
            "base_url": "http://127.0.0.1:5031",
            "token": "wf_douyin_flow_2026",
        },
        "douyin": {
            "enabled": True,                # 平台开关（关闭后不识别抖音链接）
            "parse_mode": "real",           # "real"=真实解析 | "fake"=测试视频占位
            "download_dir": VIDEO_DIR,
            "max_retry": 3,
            "retry_interval": 4,
        },
        "bilibili": {
            "enabled": True,                # 平台开关（关闭后不识别 B站链接）
            "download_dir": VIDEO_DIR,
            "quality": 64,                  # yutto 清晰度：16=360P 32=480P 64=720P 80=1080P
            "auth": "",                     # B站 SESSDATA cookie（可选，高清/大会员需）
            "yutto_path": "",               # yutto 可执行文件路径（留空自动探测）
            "ffmpeg_path": "",              # ffmpeg 可执行文件路径（留空自动探测）
            "timeout": 600,                 # 下载超时（秒）
            "max_retry": 2,
        },
        "xhs": {
            "enabled": True,                # 平台开关（关闭后不识别小红书链接）
            "download_dir": VIDEO_DIR,
            "cookie": "",                   # 小红书 cookie（可选，视频高清需）
            "xhs_root": "",                 # XHS-Downloader 源码根目录（留空用内置 tools/xhs）
            "timeout": 10,
            "max_retry": 3,
        },
        "wechat": {
            "group_whitelist": [],          # 默认空：首次运行不向任何群发送，需在 Web 面板配置
            "test_mode": False,             # True=所有发送发到文件传输助手
            "delete_after_seconds": 180,    # 发送后延迟删除秒数；<=0 永不删除
            "quote_reply": True,            # True=发送视频/图文时引用对方消息
        },
        "advanced": {
            "port": 8765,
            "listen_push": True,            # 启用 WeFlow 主动推送（SSE，实时）
            "listen_poll": True,            # 启用轮询兜底（可监听到自己发送的消息）
            "poll_interval": 3,             # 轮询间隔（秒）
            "lookback_limit": 10,           # 每会话扫描最近消息条数
            "active_window": 86400,         # 只看最近 N 秒内有消息的会话
            "log_level": "INFO",
            "max_log_lines": 500,
            "auto_open_browser": True,
        },
    }


_lock = threading.RLock()
_config = None


def _merge_defaults(cfg):
    """把旧版配置合并进默认结构，保证缺少的字段有默认值（向前兼容）。"""
    base = _default_config()
    for section, default in base.items():
        if section not in cfg:
            cfg[section] = default
        elif isinstance(default, dict) and isinstance(cfg[section], dict):
            for k, v in default.items():
                if k not in cfg[section]:
                    cfg[section][k] = v
    return cfg


def _migrate_legacy(cfg):
    """首次运行：从旧项目文件自动迁移数据（不要求用户手动复制）。"""
    changed = False

    # 迁移根目录数据文件到 data/
    os.makedirs(DATA_DIR, exist_ok=True)
    for name, src in LEGACY_DATA_FILES.items():
        dst = os.path.join(DATA_DIR, name)
        if os.path.exists(src) and not os.path.exists(dst):
            try:
                os.replace(src, dst)
                changed = True
            except Exception:
                pass

    return changed


def load_config():
    """加载配置（进程内缓存）。首次运行自动创建默认配置并写入磁盘。"""
    global _config
    with _lock:
        if _config is not None:
            return _config
        cfg = None
        existed = os.path.exists(CONFIG_FILE)
        if existed:
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
            except Exception:
                cfg = None
        if cfg is None:
            cfg = _default_config()
        cfg = _merge_defaults(cfg)
        _migrate_legacy(cfg)
        _config = cfg
        # 保证目录存在
        for d in (CONFIG_DIR, DATA_DIR, LOG_DIR, VIDEO_DIR):
            try:
                os.makedirs(d, exist_ok=True)
            except Exception:
                pass
        if not existed:
            save_config(cfg)   # 首次运行：把默认配置（含迁移的数据）写入磁盘
        return cfg


def get_config():
    """获取当前配置 dict（直接返回内部引用，调用方不得擅自修改）。"""
    if _config is None:
        load_config()
    return _config


def reload_config():
    """强制重新从磁盘加载（丢弃缓存）。"""
    global _config
    with _lock:
        _config = None
    return load_config()


def save_config(cfg):
    """保存配置到磁盘并刷新缓存。"""
    global _config
    with _lock:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        tmp = CONFIG_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        os.replace(tmp, CONFIG_FILE)
        _config = cfg


def update_config(partial):
    """用前端提交的部分字段更新配置（浅层按 section 合并），返回新配置。

    partial 形如 {"weflow": {"token": "..."}, "advanced": {"port": 8765}}。
    敏感字段为空字符串表示"保持原值不修改"。
    """
    cfg = copy.deepcopy(get_config())
    for section, fields in (partial or {}).items():
        if section not in cfg:
            cfg[section] = {}
        if not isinstance(fields, dict):
            continue
        for k, v in fields.items():
            if k in SENSITIVE_KEYS and (v is None or (isinstance(v, str) and not v.strip())):
                continue  # 空值=不修改敏感字段
            cfg[section][k] = v
    # 类型校正：数值字段
    _coerce_types(cfg)
    save_config(cfg)
    return cfg


def _coerce_types(cfg):
    """把前端字符串数字转回正确类型，容错处理。"""
    def _num(v, default):
        try:
            return int(v)
        except (TypeError, ValueError):
            try:
                return float(v)
            except (TypeError, ValueError):
                return default
    adv = cfg.get("advanced", {})
    adv["port"] = _num(adv.get("port"), 8765)
    adv["listen_push"] = bool(adv.get("listen_push", True))
    adv["listen_poll"] = bool(adv.get("listen_poll", True))
    adv["poll_interval"] = _num(adv.get("poll_interval"), 3)
    adv["lookback_limit"] = _num(adv.get("lookback_limit"), 10)
    adv["active_window"] = _num(adv.get("active_window"), 86400)
    adv["max_log_lines"] = _num(adv.get("max_log_lines"), 500)
    adv["auto_open_browser"] = bool(adv.get("auto_open_browser"))
    dy = cfg.get("douyin", {})
    dy["enabled"] = bool(dy.get("enabled", True))
    dy["max_retry"] = _num(dy.get("max_retry"), 3)
    dy["retry_interval"] = _num(dy.get("retry_interval"), 4)
    bl = cfg.get("bilibili", {})
    bl["enabled"] = bool(bl.get("enabled", True))
    bl["quality"] = _num(bl.get("quality"), 64)
    bl["timeout"] = _num(bl.get("timeout"), 600)
    bl["max_retry"] = _num(bl.get("max_retry"), 2)
    xh = cfg.get("xhs", {})
    xh["enabled"] = bool(xh.get("enabled", True))
    xh["timeout"] = _num(xh.get("timeout"), 10)
    xh["max_retry"] = _num(xh.get("max_retry"), 3)
    wc = cfg.get("wechat", {})
    wc["test_mode"] = bool(wc.get("test_mode"))
    wc["delete_after_seconds"] = _num(wc.get("delete_after_seconds"), 180)
    wc["quote_reply"] = bool(wc.get("quote_reply", True))
    if not isinstance(wc.get("group_whitelist"), list):
        wc["group_whitelist"] = []


def mask_secret(value):
    """脱敏：非空字符串返回 MASK，空返回空。"""
    if value is None:
        return ""
    return MASK if str(value).strip() else ""


def masked_config():
    """返回脱敏后的配置副本（用于 GET /api/config），并附带敏感字段"是否已配置"标记。"""
    cfg = copy.deepcopy(get_config())
    token = cfg.get("weflow", {}).get("token", "")
    cfg["weflow"]["token"] = mask_secret(token)
    cfg["_meta"] = {
        "token_set": bool(str(token).strip()),
        "config_file": CONFIG_FILE,
    }
    return cfg


def raw_secrets():
    """返回真实敏感值（仅供本地前端"显示"按钮调用，服务仅监听 127.0.0.1）。"""
    cfg = get_config()
    return {
        "token": cfg.get("weflow", {}).get("token", ""),
    }
