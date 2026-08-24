# -*- coding: utf-8 -*-
"""
配置加载、保存与校验模块。

配置文件路径优先级：
  1. 当前工作目录下的 config/config.json
  2. 项目根目录下的 config/config.json
  3. 若均不存在，基于 config/config.example.json 自动创建一份初始配置

本模块保证线程安全，并在写入时使用原子重命名避免文件损坏。
"""
import json
import os
import shutil
import threading
from core.logger import logger

_CONFIG_LOCK = threading.Lock()
_CONFIG_CACHE = None

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_DIR = os.path.join(ROOT_DIR, "config")
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")
EXAMPLE_PATH = os.path.join(CONFIG_DIR, "config.example.json")
DATA_DIR = os.path.join(ROOT_DIR, "data")
VIDEO_DIR = os.path.join(ROOT_DIR, "videos")


def _default_config():
    """当 example 也不存在时的兜底默认值。"""
    return {
        "weflow": {
            "api_base": "http://127.0.0.1:8765",
            "token": "",
            "poll_interval": 3,
            "mode": "poll",
            "weflow_enabled": False,
        },
        "douyin": {
            "enabled": True,
            "download_dir": VIDEO_DIR,
            "cookie": "",
            "max_video_mb": 100,
            "timeout": 60,
            "max_retry": 3,
        },
        "bilibili": {
            "enabled": True,
            "download_dir": VIDEO_DIR,
            "sessdata": "",
            "auth": "",
            "yutto_path": "",
            "timeout": 180,
            "max_retry": 3,
        },
        "xhs": {
            "enabled": True,
            "download_dir": VIDEO_DIR,
            "cookie": "",
            "max_video_mb": 100,
            "timeout": 60,
            "max_retry": 3,
        },
        "wechat": {
            "group_whitelist": [],          # 默认空：首次运行不向任何群发送，需在 Web 面板配置
            "test_mode": False,             # True=所有发送发到文件传输助手
            "enable_friends": False,        # 是否允许私聊转发
            "file_transfer_fallback": False,# 发送失败时是否兜底发给文件传输助手
            "quote_reply": True,            # 发送时是否引用原消息
            "quote_keywords": ["抖音", "douyin", "v.douyin.com", "iesdouyin.com"],
            "quote_timeout": 300,
            "delete_after_send": True,      # 发送成功后是否延迟删除视频
            "delete_delay": 180,            # 延迟删除秒数（默认 180 秒 = 3 分钟）
            "send_delay": 1.0,              # 发送成功后等待秒数，避免触发微信频控
        },
        "advanced": {
            "port": 8765,
            "auto_open_browser": True,
            "debug": False,
            "poll_interval": 3,
        },
    }


def ensure_directories():
    """确保运行时所需目录存在。"""
    for d in (CONFIG_DIR, DATA_DIR, VIDEO_DIR):
        os.makedirs(d, exist_ok=True)


def init_config():
    """首次运行时，若 config.json 不存在，从 example 复制或生成默认配置。"""
    ensure_directories()
    if not os.path.exists(CONFIG_PATH):
        if os.path.exists(EXAMPLE_PATH):
            try:
                shutil.copyfile(EXAMPLE_PATH, CONFIG_PATH)
                logger.info(f"[配置] 已从 {EXAMPLE_PATH} 初始化 {CONFIG_PATH}")
                return
            except Exception as e:
                logger.warning(f"[配置] 复制 example 配置失败: {e}，将使用内置默认配置")
        # 兜底写入默认配置
        try:
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(_default_config(), f, ensure_ascii=False, indent=2)
            logger.info(f"[配置] 已生成默认配置文件: {CONFIG_PATH}")
        except Exception as e:
            logger.error(f"[配置] 创建默认配置文件失败: {e}")


def _deep_merge(base, override):
    """递归合并字典，以 override 为准，保留 base 中新增的默认键。"""
    merged = dict(base)
    for k, v in override.items():
        if k in merged and isinstance(merged[k], dict) and isinstance(v, dict):
            merged[k] = _deep_merge(merged[k], v)
        else:
            merged[k] = v
    return merged


def get_config(reload=False):
    """
    获取全局配置字典（线程安全）。
    若配置文件尚未创建，会自动初始化；读取后合并默认值保证字段完整。
    """
    global _CONFIG_CACHE
    with _CONFIG_LOCK:
        if _CONFIG_CACHE is not None and not reload:
            return _CONFIG_CACHE

        init_config()
        cfg = _default_config()

        if os.path.exists(CONFIG_PATH):
            try:
                with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                    user_cfg = json.load(f)
                if isinstance(user_cfg, dict):
                    cfg = _deep_merge(cfg, user_cfg)
            except Exception as e:
                logger.error(f"[配置] 读取 {CONFIG_PATH} 失败: {e}，使用默认配置")

        _coerce_types(cfg)
        _CONFIG_CACHE = cfg
        return _CONFIG_CACHE


def save_config(new_cfg):
    """
    保存配置到 config.json（原子写入 + 刷新内存缓存）。
    返回 (ok: bool, message: str)
    """
    global _CONFIG_CACHE
    if not isinstance(new_cfg, dict):
        return False, "配置必须是 JSON 对象"

    ensure_directories()
    with _CONFIG_LOCK:
        # 合并当前默认值保证结构完整
        merged = _deep_merge(_default_config(), new_cfg)
        _coerce_types(merged)

        tmp_path = CONFIG_PATH + ".tmp"
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(merged, f, ensure_ascii=False, indent=2)
            # 原子重命名（Windows 上若目标存在可能报错，先尝试 replace）
            if os.path.exists(CONFIG_PATH):
                os.replace(tmp_path, CONFIG_PATH)
            else:
                os.rename(tmp_path, CONFIG_PATH)
            _CONFIG_CACHE = merged
            logger.info("[配置] 配置已成功保存并重新加载")
            return True, "配置保存成功"
        except Exception as e:
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass
            logger.error(f"[配置] 保存配置失败: {e}")
            return False, f"保存失败: {e}"


def _coerce_types(cfg):
    """防御性类型转换，避免前端传入字符串数字导致下游异常。"""
    adv = cfg.get("advanced", {})
    adv["port"] = int(adv.get("port", 8765))
    adv["auto_open_browser"] = bool(adv.get("auto_open_browser", True))
    adv["debug"] = bool(adv.get("debug", False))
    adv["poll_interval"] = max(1, int(adv.get("poll_interval", 3)))

    wf = cfg.get("weflow", {})
    wf["poll_interval"] = max(1, int(wf.get("poll_interval", 3)))
    wf["mode"] = str(wf.get("mode", "poll")).lower()
    wf["weflow_enabled"] = bool(wf.get("weflow_enabled", False))

    dy = cfg.get("douyin", {})
    dy["enabled"] = bool(dy.get("enabled", True))
    dy["max_video_mb"] = int(dy.get("max_video_mb", 100))
    dy["timeout"] = int(dy.get("timeout", 60))
    dy["max_retry"] = int(dy.get("max_retry", 3))

    bili = cfg.get("bilibili", {})
    bili["enabled"] = bool(bili.get("enabled", True))
    bili["timeout"] = int(bili.get("timeout", 180))
    bili["max_retry"] = int(bili.get("max_retry", 3))

    xhs = cfg.get("xhs", {})
    xhs["enabled"] = bool(xhs.get("enabled", True))
    xhs["max_video_mb"] = int(xhs.get("max_video_mb", 100))
    xhs["timeout"] = int(xhs.get("timeout", 60))
    xhs["max_retry"] = int(xhs.get("max_retry", 3))

    wc = cfg.get("wechat", {})
    wc["test_mode"] = bool(wc.get("test_mode", False))
    wc["enable_friends"] = bool(wc.get("enable_friends", False))
    wc["file_transfer_fallback"] = bool(wc.get("file_transfer_fallback", False))
    wc["delete_after_send"] = bool(wc.get("delete_after_send", True))
    wc["delete_delay"] = max(0, int(wc.get("delete_delay", 180)))
    wc["send_delay"] = max(0.0, float(wc.get("send_delay", 1.0)))
    wc["quote_timeout"] = max(10, int(wc.get("quote_timeout", 300)))
    wc["quote_reply"] = bool(wc.get("quote_reply", True))
    if not isinstance(wc.get("group_whitelist"), list):
        wc["group_whitelist"] = []


def mask_secret(value):
    """前端安全脱敏：保留前 3 后 3，中间打码。空或极短串直接返回掩码。"""
    if not value:
        return ""
    s = str(value)
    if len(s) <= 6:
        return "******"
    return f"{s[:3]}****{s[-3:]}"


def public_config():
    """
    返回供 Web 前端展示的配置字典（敏感字段脱敏）。
    """
    cfg = json.loads(json.dumps(get_config()))
    # 对 Token 脱敏（若用户未修改则保存时保持原值）
    wf = cfg.get("weflow", {})
    if wf.get("token"):
        wf["token_masked"] = mask_secret(wf["token"])
        wf["has_token"] = bool(wf["token"])
    return cfg


def raw_secrets():
    """读取未脱敏的敏感字段映射，供保存时比对还原。"""
    cfg = get_config()
    return {
        "token": cfg.get("weflow", {}).get("token", ""),
    }
