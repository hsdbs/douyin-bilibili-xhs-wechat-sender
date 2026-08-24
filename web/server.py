# -*- coding: utf-8 -*-
"""
本地 Web 管理面板后端。

- 纯标准库实现（http.server.ThreadingHTTPServer），零额外依赖，便于 PyInstaller 打包
- 默认仅监听 127.0.0.1
- 后台 worker 用独立线程运行微信监听业务，与 Web 服务互不阻塞
"""
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from core.config import (
    get_config, masked_config, raw_secrets, update_config, reload_config, STATIC_DIR,
)
from core.logger import logger
from core import state, tasks
import main as biz


class WorkerManager:
    """管理后台微信监听线程。"""

    def __init__(self):
        self._thread = None
        self._stop_event = threading.Event()
        self._lock = threading.RLock()

    def is_running(self):
        with self._lock:
            return self._thread is not None and self._thread.is_alive()

    def start(self):
        with self._lock:
            if self.is_running():
                return False, "监听已在运行中"
            self._stop_event = threading.Event()
            t = threading.Thread(target=self._run, name="wechat-listener", daemon=True)
            self._thread = t
            t.start()
        return True, "监听已启动"

    def stop(self):
        with self._lock:
            if not self.is_running():
                return False, "监听未在运行"
            self._stop_event.set()
            t = self._thread
        t.join(timeout=15)
        if t.is_alive():
            return True, "已请求停止，正在等待当前任务完成"
        with self._lock:
            self._thread = None
        return True, "监听已停止"

    def restart(self):
        ok1, msg1 = self.stop()
        ok2, msg2 = self.start()
        return ok2, f"{msg1}；{msg2}"

    def _run(self):
        state.set_service(True, started_at=time.time())
        try:
            biz.run_worker(self._stop_event)
        except Exception:
            logger.error("监听线程异常退出:\n" + __import__("traceback").format_exc())
        finally:
            state.set_service(False)


worker = WorkerManager()


def _json_response(handler, obj, code=200):
    body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    handler.send_response(code)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(body)


def _ok(handler, data=None):
    _json_response(handler, {"ok": True, "data": data})


def _err(handler, message, code=200):
    _json_response(handler, {"ok": False, "error": message}, code=code)


def _read_json_body(handler):
    try:
        length = int(handler.headers.get("Content-Length", 0))
    except ValueError:
        length = 0
    if length <= 0:
        return {}
    raw = handler.rfile.read(length)
    try:
        return json.loads(raw.decode("utf-8"))
    except Exception:
        return {}


def _static_content(path):
    """读取静态文件内容与类型。"""
    root = os.path.realpath(STATIC_DIR)
    # 规范化并防目录穿越
    full = os.path.realpath(os.path.join(root, path.lstrip("/")))
    if not (full == root or full.startswith(root + os.sep)):
        return None, None
    if not os.path.isfile(full):
        return None, None
    ext = os.path.splitext(full)[1].lower()
    ctype = {
        ".html": "text/html; charset=utf-8",
        ".css": "text/css; charset=utf-8",
        ".js": "application/javascript; charset=utf-8",
        ".svg": "image/svg+xml",
        ".png": "image/png",
        ".ico": "image/x-icon",
    }.get(ext, "application/octet-stream")
    with open(full, "rb") as f:
        return f.read(), ctype


class Handler(BaseHTTPRequestHandler):
    server_version = "DouyinSender/1.0"

    # ---- 工具 ----
    def _send_static(self, path):
        data, ctype = _static_content(path)
        if data is None:
            self.send_response(404)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"404 Not Found")
            return
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    # ---- 日志 ----
    def log_message(self, fmt, *args):
        # 屏蔽默认 stderr 访问日志（本地管理面板不需要，且避免噪音）
        pass

    # ---- 路由 ----
    def do_GET(self):
        path = self.path.split("?")[0].rstrip("/") or "/"
        qs = dict()
        if "?" in self.path:
            from urllib.parse import parse_qs, urlparse
            qs = {k: v[0] for k, v in parse_qs(urlparse(self.path).query).items()}

        if path == "/" or path == "/index.html":
            self._send_static("index.html")
        elif path.startswith("/static/"):
            self._send_static(path[len("/static/"):])
        elif path in ("/css/style.css", "/js/app.js", "/favicon.ico"):
            self._send_static(path[1:])
        elif path == "/api/status":
            _ok(self, state.snapshot())
        elif path == "/api/config":
            _ok(self, masked_config())
        elif path == "/api/config/secrets":
            _ok(self, raw_secrets())
        elif path == "/api/logs":
            try:
                since = int(qs.get("since", 0))
            except ValueError:
                since = 0
            lines = logger.get_lines(since)
            _ok(self, {"lines": lines, "seq": lines[-1]["seq"] if lines else since})
        elif path == "/api/tasks":
            try:
                limit = int(qs.get("limit", 100))
            except ValueError:
                limit = 100
            _ok(self, {"tasks": tasks.list_tasks(limit)})
        elif path == "/api/stats":
            _ok(self, tasks.today_stats())
        elif path == "/api/service":
            _ok(self, state.get_service())
        elif path == "/api/about":
            _ok(self, {
                "name": "抖音视频自动发送",
                "version": "1.0.0",
                "service_running": worker.is_running(),
                "config_file": get_config() and "config/config.json",
                "listen_host": "127.0.0.1",
            })
        elif path == "/api/env/check":
            _ok(self, _env_check())
        elif path == "/api/fs/list":
            target_path = qs.get("path", "")
            _ok(self, _list_filesystem(target_path))
        else:
            _err(self, "接口不存在: " + path, code=404)

    def do_POST(self):
        path = self.path.split("?")[0].rstrip("/") or "/"

        if path == "/api/config":
            partial = _read_json_body(self)
            try:
                cfg = update_config(partial)
                _ok(self, masked_config())
                logger.info("[配置] 配置已保存")
            except Exception as e:
                logger.error(f"[配置] 保存失败: {e}")
                _err(self, f"配置保存失败: {e}")
        elif path == "/api/config/reload":
            try:
                reload_config()
                _ok(self, masked_config())
            except Exception as e:
                _err(self, f"重载失败: {e}")
        elif path == "/api/weflow/test":
            state.set_status("weflow", "checking", "正在测试 WeFlow 连接...")
            ok, detail = _safe_test(biz.test_weflow)
            state.set_status("weflow", "ok" if ok else "error", detail)
            _json_response(self, {"ok": ok, "detail": detail, "status": "ok" if ok else "error"})
        elif path == "/api/douyin/test":
            state.set_status("douyin", "checking", "正在测试抖音解析...")
            ok, detail = _safe_test(biz.test_douyin)
            state.set_status("douyin", "ok" if ok else "error", detail)
            _json_response(self, {"ok": ok, "detail": detail, "status": "ok" if ok else "error"})
        elif path == "/api/bilibili/test":
            state.set_status("bilibili", "checking", "正在测试 B站解析...")
            ok, detail = _safe_test(biz.test_bilibili)
            state.set_status("bilibili", "ok" if ok else "error", detail)
            _json_response(self, {"ok": ok, "detail": detail, "status": "ok" if ok else "error"})
        elif path == "/api/xhs/test":
            state.set_status("xhs", "checking", "正在测试小红书解析...")
            ok, detail = _safe_test(biz.test_xhs)
            state.set_status("xhs", "ok" if ok else "error", detail)
            _json_response(self, {"ok": ok, "detail": detail, "status": "ok" if ok else "error"})
        elif path == "/api/netease/test":
            state.set_status("netease", "checking", "正在测试网易云解析...")
            import music_parser
            ok, detail = _safe_test(music_parser.test_netease_api)
            state.set_status("netease", "ok" if ok else "error", detail)
            _json_response(self, {"ok": ok, "detail": detail, "status": "ok" if ok else "error"})
        elif path == "/api/qqmusic/test":
            state.set_status("qqmusic", "checking", "正在测试 QQ音乐解析...")
            import music_parser
            ok, detail = _safe_test(music_parser.test_music_env)
            state.set_status("qqmusic", "ok" if ok else "error", detail)
            _json_response(self, {"ok": ok, "detail": detail, "status": "ok" if ok else "error"})
        elif path in ("/api/ebook/test", "/api/novel/test", "/api/book/test"):
            state.set_status("ebook", "checking", "正在测试电子书检索下载引擎...")
            import novel_parser
            ok, detail = _safe_test(novel_parser.test_novel)
            state.set_status("ebook", "ok" if ok else "error", detail)
            _json_response(self, {"ok": ok, "detail": detail, "status": "ok" if ok else "error"})
        elif path == "/api/wechat/test":
            state.set_status("wechat", "checking", "正在测试微信连接...")
            ok, detail = _safe_test(biz.test_wechat)
            state.set_status("wechat", "ok" if ok else "error", detail)
            _json_response(self, {"ok": ok, "detail": detail, "status": "ok" if ok else "error"})
        elif path == "/api/service/start":
            ok, msg = worker.start()
            if ok:
                logger.info("[服务] 监听已启动")
            _json_response(self, {"ok": ok, "detail": msg})
        elif path == "/api/service/stop":
            ok, msg = worker.stop()
            if ok:
                logger.info("[服务] 监听已停止")
            _json_response(self, {"ok": ok, "detail": msg})
        elif path == "/api/service/restart":
            ok, msg = worker.restart()
            logger.info(f"[服务] 重启监听：{msg}")
            _json_response(self, {"ok": ok, "detail": msg})
        elif path == "/api/logs/clear":
            logger.clear()
            _ok(self, {"cleared": True})
        elif path == "/api/tasks/clear":
            tasks.clear_tasks()
            _ok(self, {"cleared": True})
        elif path == "/api/select-folder":
            folder = _select_folder()
            _ok(self, {"folder": folder})
        elif path == "/api/fs/mkdir":
            data = _read_json_body(self)
            parent = data.get("parent_path", "")
            name = data.get("name", "")
            ok, res = _create_folder(parent, name)
            if ok:
                _ok(self, {"folder": res})
            else:
                _err(self, res)
        else:
            _err(self, "接口不存在: " + path, code=404)


def _safe_test(fn):
    """执行测试函数，兜底捕获异常，避免 handler 崩溃。返回 (ok, detail)。"""
    try:
        ok, detail = fn()
        return bool(ok), str(detail)
    except Exception as e:
        return False, f"测试异常: {str(e)[:160]}"


def _select_folder():
    """打开原生系统文件夹选择对话框，强制置顶显示，返回所选路径（取消或失败返回空字符串）。"""
    import subprocess
    import sys

    # 方案 1：使用 Python 自带的 tkinter filedialog（原生 Windows 对话框，强制置顶）
    try:
        py_script = (
            "import tkinter as tk, tkinter.filedialog as fd, sys, os\n"
            "r = tk.Tk()\n"
            "r.withdraw()\n"
            "r.attributes('-topmost', True)\n"
            "folder = fd.askdirectory(parent=r, title='请选择存储目录')\n"
            "r.destroy()\n"
            "if folder:\n"
            "    sys.stdout.write(os.path.normpath(folder))\n"
        )
        r = subprocess.run(
            [sys.executable, "-c", py_script],
            capture_output=True, text=True, timeout=120, encoding="utf-8", errors="ignore"
        )
        folder = (r.stdout or "").strip()
        if folder:
            return folder
    except Exception as e:
        logger.warning(f"[目录选择器] tkinter 方案异常，转入 PowerShell 方案: {e}")

    # 方案 2：PowerShell 强制 TopMost 弹窗方案
    try:
        ps_cmd = (
            "Add-Type -AssemblyName System.Windows.Forms\n"
            "$form = New-Object System.Windows.Forms.Form\n"
            "$form.TopMost = $true\n"
            "$form.Opacity = 0\n"
            "$form.Show()\n"
            "$form.Visible = $false\n"
            "$f = New-Object System.Windows.Forms.FolderBrowserDialog\n"
            "$f.Description = '请选择存储目录'\n"
            "$f.ShowNewFolderButton = $true\n"
            "$r = $f.ShowDialog($form)\n"
            "if ($r -eq [System.Windows.Forms.DialogResult]::OK) { [Console]::Out.Write($f.SelectedPath) }\n"
            "$form.Dispose()\n"
        )
        r = subprocess.run(
            ["powershell.exe", "-NoProfile", "-STA", "-Command", ps_cmd],
            capture_output=True, timeout=120,
        )
        raw = r.stdout
        text = ""
        for enc in ("utf-8", "gbk", "mbcs", "cp936"):
            try:
                text = raw.decode(enc)
                break
            except Exception:
                continue
        return text.strip()
    except Exception as e:
        logger.error(f"[目录选择器] 打开目录选择失败: {e}")
        return ""


def _list_filesystem(target_path=None):
    """列出系统驱动器或指定路径下的子目录列表（用于内置可视化目录树选择器）。"""
    import os
    import string

    # 获取可用驱动器列表（Windows）
    drives = []
    if os.name == "nt":
        try:
            import ctypes
            bitmask = ctypes.windll.kernel32.GetLogicalDrives()
            for letter in string.ascii_uppercase:
                if bitmask & 1:
                    drive_path = f"{letter}:\\"
                    drives.append({"name": f"{letter}: 盘", "path": drive_path})
                bitmask >>= 1
        except Exception:
            for letter in ("C", "D", "E", "F"):
                p = f"{letter}:\\"
                if os.path.exists(p):
                    drives.append({"name": f"{letter}: 盘", "path": p})
    else:
        drives.append({"name": "根目录 /", "path": "/"})

    # 当前项目根目录
    project_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    # 如果未指定 path 或路径不存在，默认使用项目目录
    if not target_path or not os.path.exists(target_path):
        target_path = project_dir

    target_path = os.path.normpath(target_path)

    # 计算父级目录
    parent_path = os.path.dirname(target_path)
    if parent_path == target_path:
        parent_path = None

    items = []
    try:
        with os.scandir(target_path) as it:
            for entry in it:
                try:
                    if entry.is_dir(follow_symlinks=False):
                        name = entry.name
                        # 过滤隐藏系统目录
                        if name.startswith(".") or name.startswith("$") or name in ("System Volume Information", "Recovery", "$RECYCLE.BIN"):
                            continue
                        items.append({
                            "name": name,
                            "path": os.path.normpath(entry.path),
                        })
                except (PermissionError, OSError):
                    continue
        items.sort(key=lambda x: x["name"].lower())
    except (PermissionError, OSError) as e:
        logger.warning(f"[文件系统] 访问目录受限 {target_path}: {e}")

    return {
        "current_path": target_path,
        "parent_path": parent_path,
        "drives": drives,
        "folders": items,
        "project_dir": project_dir
    }


def _create_folder(parent_path, name):
    """在指定目录下创建新子文件夹。"""
    import os
    if not parent_path or not os.path.exists(parent_path):
        return False, "父级目录不存在"
    name = (name or "").strip()
    if not name or any(c in name for c in r'\/:*?"<>|'):
        return False, "文件夹名称为空或包含非法字符"
    new_dir = os.path.normpath(os.path.join(parent_path, name))
    try:
        os.makedirs(new_dir, exist_ok=True)
        return True, new_dir
    except Exception as e:
        return False, f"创建文件夹失败: {e}"


def _env_check():
    """环境检查：配置 / Web / WeFlow / 微信 / 抖音解析。"""
    result = []

    # 配置文件
    cfg_file = _cfg_file()
    cfg_ok = os.path.exists(cfg_file)
    result.append({"name": "配置文件", "status": "ok" if cfg_ok else "error",
                   "detail": "config/config.json" if cfg_ok else "未找到配置文件"})

    # Web 服务（自身）
    result.append({"name": "Web 服务", "status": "ok", "detail": "运行中"})

    # WeFlow
    ok, detail = biz.test_weflow()
    result.append({"name": "WeFlow", "status": "ok" if ok else "error", "detail": detail})

    # 微信
    ok, detail = biz.test_wechat()
    result.append({"name": "微信", "status": "ok" if ok else "error", "detail": detail})

    # 抖音解析（自动游客态，无需配置 Cookie）
    result.append({"name": "抖音解析", "status": "ok",
                   "detail": "自动获取游客态 Cookie（无需配置）"})

    # B站解析（yutto + FFmpeg）
    ok, detail = biz.test_bilibili()
    result.append({"name": "B站解析", "status": "ok" if ok else "error", "detail": detail})

    # 小红书解析（XHS-Downloader）
    ok, detail = biz.test_xhs()
    result.append({"name": "小红书解析", "status": "ok" if ok else "error", "detail": detail})

    # 音乐解析（yt-dlp + FFmpeg，网易云 / QQ音乐共用）
    import music_parser
    ok, detail = music_parser.test_music_env()
    result.append({"name": "音乐解析(网易云/QQ)", "status": "ok" if ok else "error", "detail": detail})

    # 电子书引擎（小说 / 出版名著高速检索下载）
    import ebook_engine
    ok, detail = ebook_engine.test_ebook_engine()
    result.append({"name": "电子书检索下载", "status": "ok" if ok else "error", "detail": detail})

    return {"items": result}


def _cfg_file():
    from core.config import CONFIG_FILE
    return CONFIG_FILE


def create_server(port=None):
    """创建并返回 HTTP 服务器（不启动）。"""
    cfg = get_config()
    port = port or int(cfg.get("advanced", {}).get("port", 8765))
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    httpd.daemon_threads = True
    return httpd, port
