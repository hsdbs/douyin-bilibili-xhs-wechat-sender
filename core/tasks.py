# -*- coding: utf-8 -*-
"""
任务/处理记录 + 今日统计。

- 每次处理一条抖音链接时，worker 记录一条任务（时间、来源、链接、视频、状态、错误）
- 持久化到 data/tasks.json，保留最近 N 条
- 提供今日统计（处理数 / 成功 / 失败 / 下载数），跨天自动重置
"""
import json
import os
import threading
import time

from .config import DATA_DIR, get_config

TASKS_FILE = os.path.join(DATA_DIR, "tasks.json")
MAX_TASKS = 300

_lock = threading.Lock()
_tasks = None       # 延迟加载
_today = time.strftime("%Y-%m-%d")


def _load():
    global _tasks
    if _tasks is not None:
        return _tasks
    _tasks = []
    if os.path.exists(TASKS_FILE):
        try:
            with open(TASKS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                _tasks = data
        except Exception:
            _tasks = []
    return _tasks


def _save():
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        tmp = TASKS_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(_tasks, f, ensure_ascii=False, indent=2)
        os.replace(tmp, TASKS_FILE)
    except Exception:
        pass


def add_task(source, url, status="pending", video="", error=""):
    """新增一条任务记录，返回 task id。"""
    global _today
    _today = time.strftime("%Y-%m-%d")
    with _lock:
        tasks = _load()
        task = {
            "id": int(time.time() * 1000),
            "ts": time.time(),
            "time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "source": source,
            "url": url,
            "video": video,
            "status": status,       # pending / processing / success / failed / deleted
            "error": error,
        }
        tasks.append(task)
        if len(tasks) > MAX_TASKS:
            tasks[:] = tasks[-MAX_TASKS:]
        _save()
        return task


def update_task(task_id, status=None, video=None, error=None):
    with _lock:
        tasks = _load()
        for t in reversed(tasks):
            if t.get("id") == task_id:
                if status is not None:
                    t["status"] = status
                if video is not None:
                    t["video"] = video
                if error is not None:
                    t["error"] = error
                break
        _save()


def list_tasks(limit=100):
    with _lock:
        tasks = _load()
        return list(reversed(tasks[-limit:]))


def clear_tasks():
    global _tasks
    with _lock:
        _tasks = []
        _save()


def today_stats():
    """今日统计（按 status 分组）。"""
    today = time.strftime("%Y-%m-%d")
    with _lock:
        tasks = _load()
    stats = {"total": 0, "success": 0, "failed": 0, "downloaded": 0, "pending": 0, "processing": 0, "deleted": 0}
    for t in tasks:
        if t.get("time", "").startswith(today):
            stats["total"] += 1
            st = t.get("status", "")
            if st == "success":
                stats["success"] += 1
            elif st == "failed":
                stats["failed"] += 1
            elif st == "deleted":
                stats["deleted"] += 1
            elif st == "processing":
                stats["processing"] += 1
            elif st == "pending":
                stats["pending"] += 1
            if t.get("video"):
                stats["downloaded"] += 1
    return stats
