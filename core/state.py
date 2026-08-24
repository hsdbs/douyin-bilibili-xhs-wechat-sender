# -*- coding: utf-8 -*-
"""
运行时状态管理：各外部依赖（微信 / WeFlow / 抖音解析）连接状态 + 监听服务运行状态。

状态值：'unknown' | 'ok' | 'error' | 'checking'
"""
import threading
import time

_lock = threading.Lock()

_state = {
    "weflow": {"status": "unknown", "detail": "", "checked_at": 0},
    "wechat": {"status": "unknown", "detail": "", "checked_at": 0},
    "douyin": {"status": "unknown", "detail": "", "checked_at": 0},
    "bilibili": {"status": "unknown", "detail": "", "checked_at": 0},
    "xhs": {"status": "unknown", "detail": "", "checked_at": 0},
    "netease": {"status": "unknown", "detail": "", "checked_at": 0},
    "qqmusic": {"status": "unknown", "detail": "", "checked_at": 0},
    "ebook": {"status": "unknown", "detail": "", "checked_at": 0},
    "service": {
        "running": False,
        "started_at": None,      # 启动时间戳
        "pid": None,
    },
}


def set_status(module, status, detail=""):
    with _lock:
        _state[module]["status"] = status
        _state[module]["detail"] = detail or ""
        _state[module]["checked_at"] = time.time()


def get_module_status(module):
    with _lock:
        return dict(_state[module])


def set_service(running, started_at=None, pid=None):
    with _lock:
        if running:
            _state["service"]["running"] = True
            _state["service"]["started_at"] = started_at or time.time()
            _state["service"]["pid"] = pid
        else:
            _state["service"]["running"] = False
            _state["service"]["started_at"] = None


def get_service():
    with _lock:
        return dict(_state["service"])


def uptime_seconds():
    s = get_service()
    if not s["running"] or not s["started_at"]:
        return 0
    return max(0, int(time.time() - s["started_at"]))


def snapshot():
    """返回完整状态快照（供 /api/status）。"""
    with _lock:
        svc = dict(_state["service"])
    uptime = 0
    if svc["running"] and svc["started_at"]:
        uptime = max(0, int(time.time() - svc["started_at"]))
    svc["uptime"] = uptime
    return {
        "weflow": dict(_state["weflow"]),
        "wechat": dict(_state["wechat"]),
        "douyin": dict(_state["douyin"]),
        "bilibili": dict(_state["bilibili"]),
        "xhs": dict(_state["xhs"]),
        "netease": dict(_state["netease"]),
        "qqmusic": dict(_state["qqmusic"]),
        "ebook": dict(_state.get("ebook", {"status": "unknown", "detail": "", "checked_at": 0})),
        "service": svc,
        "server_time": time.time(),
    }
