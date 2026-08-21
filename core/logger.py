# -*- coding: utf-8 -*-
"""
统一日志管理器。

- 环形缓冲保留最近 N 条日志（供 Web 日志页轮询）
- 支持 INFO / WARNING / ERROR / DEBUG 分级
- 记录前自动脱敏（替换 WeFlow Token）
- 同步写文件（logs/），并按标准库 logging 输出到控制台
"""
import logging
import os
import sys
import threading
import time

from .config import LOG_DIR, get_config


class LogManager:
    def __init__(self):
        self._lock = threading.Lock()
        self._buffer = []          # list of dict {seq, time, level, message}
        self._seq = 0
        self._max_lines = 500
        self._console = logging.getLogger("douyin-sender")
        if not self._console.handlers:
            self._console.setLevel(logging.INFO)
            # windowed 打包（无控制台）时 sys.stderr 可能为 None，改用 NullHandler 兜底
            try:
                h = logging.StreamHandler(sys.stderr) if sys.stderr else logging.NullHandler()
            except Exception:
                h = logging.NullHandler()
            h.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%H:%M:%S"))
            self._console.addHandler(h)
            self._console.propagate = False
        self._file_handler = None
        self._log_file = None

    # ---- 内部 ----
    def _mask(self, text):
        """替换敏感信息。"""
        if not isinstance(text, str):
            return text
        try:
            cfg = get_config()
            token = cfg.get("weflow", {}).get("token", "")
            if token and len(token) > 3:
                text = text.replace(token, "******")
        except Exception:
            pass
        return text

    def _max_lines_value(self):
        try:
            return int(get_config().get("advanced", {}).get("max_log_lines", 500))
        except Exception:
            return 500

    def _ensure_file(self):
        try:
            os.makedirs(LOG_DIR, exist_ok=True)
            today = time.strftime("%Y-%m-%d")
            path = os.path.join(LOG_DIR, f"app_{today}.log")
            if path != self._log_file:
                if self._file_handler:
                    self._console.removeHandler(self._file_handler)
                    try:
                        self._file_handler.close()
                    except Exception:
                        pass
                self._file_handler = logging.FileHandler(path, encoding="utf-8")
                self._file_handler.setFormatter(
                    logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%Y-%m-%d %H:%M:%S"))
                self._console.addHandler(self._file_handler)
                self._log_file = path
        except Exception:
            self._file_handler = None

    def log(self, level, message):
        message = self._mask(str(message))
        with self._lock:
            self._seq += 1
            self._max_lines = self._max_lines_value()
            self._buffer.append({
                "seq": self._seq,
                "time": time.strftime("%H:%M:%S"),
                "level": level,
                "message": message,
            })
            if len(self._buffer) > self._max_lines:
                self._buffer = self._buffer[-self._max_lines:]
        self._ensure_file()
        lv = {"DEBUG": logging.DEBUG, "INFO": logging.INFO,
              "WARNING": logging.WARNING, "ERROR": logging.ERROR}.get(level, logging.INFO)
        self._console.log(lv, message)

    def info(self, msg):
        self.log("INFO", msg)

    def warning(self, msg):
        self.log("WARNING", msg)

    def error(self, msg):
        self.log("ERROR", msg)

    def debug(self, msg):
        self.log("DEBUG", msg)

    # ---- Web 读取 ----
    def get_lines(self, since_seq=0):
        """返回 seq > since_seq 的日志（增量轮询）。since_seq=0 返回全部。"""
        with self._lock:
            if since_seq <= 0:
                return list(self._buffer)
            return [r for r in self._buffer if r["seq"] > since_seq]

    def clear(self):
        with self._lock:
            self._buffer = []


# 全局单例
logger = LogManager()
