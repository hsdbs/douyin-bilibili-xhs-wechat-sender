# -*- coding: utf-8 -*-
"""
全局运行状态与单例状态机。

提供线程安全的状态读写，用于 Web Dashboard 实时展示：
  - 各组件连接状态（WeFlow / 微信 / 抖音 / B站 / 小红书）
  - 后台任务运行状态（running / stopped / uptime）
  - 实时统计指标（总处理量、成功数、失败数）
"""
import threading
import time

_STATE_LOCK = threading.Lock()

_state = {
    "weflow": {"status": "unknown", "detail": "", "checked_at": 0},
    "wechat": {"status": "unknown", "detail": "", "checked_at": 0},
    "douyin": {"status": "unknown", "detail": "", "checked_at": 0},
    "bilibili": {"status": "unknown", "detail": "", "checked_at": 0},
    "xhs": {"status": "unknown", "detail": "", "checked_at": 0},
    "service": {
        "running": False,
        "started_at": None,      # 启动时间戳
        "pid": None,
        "uptime": 0,
    },
}


def set_status(component, status, detail=""):
    """
    更新某组件的状态。
    component: "weflow" | "wechat" | "douyin" | "bilibili" | "xhs"
    status:    "ok" | "error" | "checking" | "unknown"
    """
    with _STATE_LOCK:
        if component in _state:
            _state[component] = {
                "status": status,
                "detail": str(detail),
                "checked_at": int(time.time()),
            }


def set_service_running(running, pid=None):
    """更新后台监听服务的运行状态。"""
    with _STATE_LOCK:
        svc = _state["service"]
        if running:
            svc["running"] = True
            svc["started_at"] = time.time()
            svc["pid"] = pid
        else:
            svc["running"] = False
            svc["started_at"] = None
            svc["pid"] = None
            svc["uptime"] = 0


def is_service_running():
    with _STATE_LOCK:
        return bool(_state["service"]["running"])


def snapshot():
    """获取当前所有状态的深拷贝快照。"""
    with _STATE_LOCK:
        svc = dict(_state["service"])
        if svc["running"] and svc["started_at"]:
            svc["uptime"] = int(time.time() - svc["started_at"])
        return {
            "weflow": dict(_state["weflow"]),
            "wechat": dict(_state["wechat"]),
            "douyin": dict(_state["douyin"]),
            "bilibili": dict(_state["bilibili"]),
            "xhs": dict(_state["xhs"]),
            "service": svc,
            "server_time": time.time(),
        }
