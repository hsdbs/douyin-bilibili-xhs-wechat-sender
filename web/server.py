# -*- coding: utf-8 -*-
"""
Web 后端服务模块。

基于 Python 标准库 http.server 实现（零额外依赖，方便打包单文件/绿色免安装）。

提供 RESTful API 与静态页面托管：
  - GET  /                     -> 重定向到 /static/index.html
  - GET  /static/*             -> 托管前端 HTML/CSS/JS 资源
  - GET  /api/status           -> 综合状态（服务运行/外部依赖/今日统计）
  - GET  /api/config           -> 读取脱敏配置
  - POST /api/config           -> 更新配置并持久化
  - GET  /api/config/secrets   -> 读取明文 Token（本地调试用）
  - POST /api/control          -> 启动/停止/重启主监听 Worker
  - POST /api/test/*           -> 连通性测试（WeFlow/微信/抖音/B站/小红书/电子书）
  - GET  /api/tasks            -> 任务记录列表
  - POST /api/tasks/clear      -> 清空任务记录
  - GET  /api/logs             -> 实时日志增量获取
  - POST /api/logs/clear       -> 清空内存日志缓存
  - POST /api/fs/pick_dir      -> 打开原生系统目录选择对话框
"""
import cgi
import json
import mimetypes
import os
import sys
import threading
import time
import urllib.parse
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn

from core.config import (
    get_config, masked_config, update_config, raw_secrets,
    STATIC_DIR, BASE_DIR
)
from core.logger import logger
from core import state, tasks

_server_instance = None
_server_thread = None


class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    """多线程 HTTP 服务器，避免单个长请求（如测试连接）阻塞其它请求。"""
    daemon_threads = True
    allow_reuse_address = True


class WebHandler(BaseHTTPRequestHandler):
    """HTTP 请求处理器。"""

    server_version = "DouyinSenderWeb/1.0"

    def log_message(self, format, *args):
        # 禁用默认的 stderr 请求日志，避免刷屏；仅在需要时通过 core.logger 输出
        pass

    # ============ 辅助响应方法 ============
    def _send_json(self, code, data):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.end_headers()
        self.wfile.write(body)

    def _send_ok(self, data=None):
        self._send_json(200, {"ok": True, "data": data})

    def _send_err(self, message, code=400):
        self._send_json(code, {"ok": False, "error": str(message)})

    def _read_body_json(self):
        length = int(self.headers.get("Content-Length", 0))
        if length <= 0:
            return {}
        raw = self.rfile.read(length).decode("utf-8", errors="replace")
        try:
            return json.loads(raw)
        except Exception as e:
            raise ValueError(f"无效的 JSON 请求体: {e}")

    # ============ 路由分发 ============
    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path in ("", "/"):
            self.send_response(302)
            self.send_header("Location", "/static/index.html")
            self.end_headers()
            return

        if path.startswith("/static/"):
            self._serve_static(path[len("/static/"):])
            return

        if path == "/api/status":
            self._api_get_status()
        elif path == "/api/config":
            self._api_get_config()
        elif path == "/api/config/secrets":
            self._api_get_secrets()
        elif path == "/api/tasks":
            self._api_get_tasks()
        elif path == "/api/logs":
            query = urllib.parse.parse_qs(parsed.query)
            since = int(query.get("since", [0])[0])
            self._api_get_logs(since)
        else:
            self._send_err(f"未知 API: {path}", code=404)

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        try:
            if path == "/api/config":
                self._api_post_config()
            elif path == "/api/control":
                self._api_post_control()
            elif path.startswith("/api/test/"):
                target = path[len("/api/test/"):]
                self._api_post_test(target)
            elif path == "/api/tasks/clear":
                tasks.clear_tasks()
                self._send_ok({"cleared": True})
            elif path == "/api/logs/clear":
                logger.clear_memory_logs()
                self._send_ok({"cleared": True})
            elif path == "/api/fs/pick_dir":
                self._api_post_pick_dir()
            else:
                self._send_err(f"未知 POST 路由: {path}", code=404)
        except Exception as e:
            logger.error(f"[Web API] 处理 POST {path} 异常: {e}")
            self._send_err(str(e), code=500)

    # ============ 静态文件托管 ============
    def _serve_static(self, rel_path):
        rel_path = rel_path.lstrip("/\\")
        full_path = os.path.abspath(os.path.join(STATIC_DIR, rel_path))

        # 安全限制：防止路径遍历跳出静态目录
        if not full_path.startswith(os.path.abspath(STATIC_DIR)):
            self.send_error(403, "Forbidden")
            return

        if not os.path.exists(full_path) or os.path.isdir(full_path):
            self.send_error(404, "File Not Found")
            return

        mime, _ = mimetypes.guess_type(full_path)
        mime = mime or "application/octet-stream"

        try:
            with open(full_path, "rb") as f:
                content = f.read()
            self.send_response(200)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(content)
        except Exception as e:
            self.send_error(500, f"Read file error: {e}")

    # ============ 具体 API 实现 ============
    def _api_get_status(self):
        s = state.get_state()
        summary = tasks.get_today_summary()
        self._send_ok({
            "state": s,
            "summary": summary,
            "version": "1.0.0",
        })

    def _api_get_config(self):
        self._send_ok(masked_config())

    def _api_get_secrets(self):
        self._send_ok(raw_secrets())

    def _api_post_config(self):
        body = self._read_body_json()
        new_cfg = update_config(body)
        logger.info("[配置] 用户已保存新配置")
        self._send_ok(masked_config())

    def _api_post_control(self):
        from main import start_listener, stop_listener, is_listener_running
        body = self._read_body_json()
        action = body.get("action", "").lower()

        if action == "start":
            start_listener()
            logger.info("[控制] 用户手动启动监听服务")
        elif action == "stop":
            stop_listener()
            logger.info("[控制] 用户手动停止监听服务")
        elif action == "restart":
            stop_listener()
            time.sleep(0.5)
            start_listener()
            logger.info("[控制] 用户重启监听服务")
        else:
            self._send_err(f"未知控制指令: {action}")
            return

        self._send_ok({
            "listener_running": is_listener_running()
        })

    def _api_post_test(self, target):
        """连通性测试分发。"""
        if target == "weflow":
            from main import test_weflow_connection
            ok, detail = test_weflow_connection()
        elif target == "wechat":
            from main import test_wechat_connection
            ok, detail = test_wechat_connection()
        elif target == "douyin":
            from douyin_parser import test_douyin
            ok, detail = test_douyin()
        elif target == "bilibili":
            from bilibili_parser import test_bilibili
            ok, detail = test_bilibili()
        elif target == "xhs":
            from xhs_parser import test_xhs
            ok, detail = test_xhs()
        elif target in ("ebook", "novel"):
            from novel_parser import test_novel
            ok, detail = test_novel()
        else:
            self._send_err(f"不支持的测试目标: {target}")
            return

        self._send_ok({"target": target, "ok": ok, "detail": detail})

    def _api_get_tasks(self):
        self._send_ok(tasks.get_tasks())

    def _api_get_logs(self, since):
        lines, latest_seq = logger.get_memory_logs(since=since)
        self._send_ok({"lines": lines, "seq": latest_seq})

    def _api_post_pick_dir(self):
        """在 Windows 下弹出目录选择框。"""
        body = self._read_body_json()
        initial = body.get("initial", "")
        selected = ""

        if sys.platform == "win32":
            try:
                import tkinter as tk
                from tkinter import filedialog
                root = tk.Tk()
                root.withdraw()
                root.attributes("-topmost", True)
                selected = filedialog.askdirectory(
                    title="选择保存目录",
                    initialdir=initial if (initial and os.path.isdir(initial)) else None
                )
                root.destroy()
            except Exception as e:
                logger.warning(f"[系统] 调用图形目录选择器异常: {e}")

        self._send_ok({"path": selected or initial})


def start_server(port=8765):
    """启动 Web 服务。"""
    global _server_instance, _server_thread
    if _server_instance:
        return _server_instance

    try:
        server = ThreadedHTTPServer(("127.0.0.1", port), WebHandler)
        _server_instance = server
        _server_thread = threading.Thread(
            target=server.serve_forever,
            daemon=True,
            name="WebServerThread"
        )
        _server_thread.start()
        return server
    except Exception as e:
        logger.error(f"[Web] 绑定端口 {port} 失败: {e}")
        return None


def stop_server():
    """停止 Web 服务。"""
    global _server_instance, _server_thread
    if _server_instance:
        try:
            _server_instance.shutdown()
            _server_instance.server_close()
        except Exception:
            pass
        _server_instance = None
    _server_thread = None
