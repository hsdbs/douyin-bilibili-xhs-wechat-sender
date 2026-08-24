# -*- coding: utf-8 -*-
"""
程序入口：抖音视频自动发送 —— 本地可视化管理系统。

启动流程：
  1. 加载配置
  2. 检查端口占用（被占用则自动换端口 / 单实例检测）
  3. 启动 Web 管理面板（仅 127.0.0.1）
  4. 自动打开浏览器进入 Dashboard

注意：此处只启动 Web 服务；微信监听由用户在面板中点击「启动监听」触发。
"""
import json
import os
import sys
import threading
import time
import urllib.request
import webbrowser

from core.config import get_config
from core.logger import logger

APP_NAME = "抖音视频自动发送"
APP_VERSION = "1.0.0"


def _probe_self(port):
    """探测某端口是否已是本程序实例（单实例检测）。"""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/about", timeout=2) as r:
            data = json.loads(r.read().decode("utf-8"))
            return (data.get("data") or {}).get("name") == APP_NAME
    except Exception:
        return False


def open_browser(port):
    url = f"http://127.0.0.1:{port}/"
    try:
        webbrowser.open(url)
        return True
    except Exception:
        return False


def _detect_system_proxy():
    """检测系统代理（环境变量优先，Windows 注册表兜底）。"""
    p = (os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
         or os.environ.get("HTTP_PROXY") or os.environ.get("http_proxy"))
    if p:
        return p
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Internet Settings") as key:
            enabled, _ = winreg.QueryValueEx(key, "ProxyEnable")
            if enabled:
                server, _ = winreg.QueryValueEx(key, "ProxyServer")
                if server:
                    # 处理可能形如 http=127.0.0.1:7890;https=127.0.0.1:7890 的复合格式
                    if "=" in server:
                        for item in server.split(";"):
                            if item.startswith("http=") or item.startswith("https="):
                                s = item.split("=", 1)[1]
                                return s if "://" in s else "http://" + s
                    return server if "://" in server else "http://" + server
    except Exception:
        pass
    return None


def _disable_system_proxy():
    """强制所有出网请求国内直连、不走系统代理。

    本机若配置了 HTTP(S)_PROXY（如 Clash 127.0.0.1:7892），会把 api.bilibili.com 等国内
    API/CDN 路由到失效上游，导致 TLS 握手超时、解析失败。清掉代理变量后，httpx / requests /
    urllib / yt_dlp 以及 yutto、小红书子进程（均继承本进程环境）一律直连。
    """
    proxy_vars = {
        "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "FTP_PROXY",
        "http_proxy", "https_proxy", "all_proxy", "ftp_proxy",
    }
    # 先保存原始代理，供需要走代理的境外站点（如维基文库 zh.wikisource.org）使用：
    # 本机清掉代理后一律国内直连，但维基文库是 .org 境外站，只有经 Clash 等代理才连得上，
    # 故在此把原始代理（环境变量优先，Windows 注册表兜底）暂存到独立变量，wikisource_parser 会读取它强制走代理。
    _orig = _detect_system_proxy()
    if _orig:
        os.environ["WORKBUDDY_ORIGINAL_HTTPS_PROXY"] = _orig
        os.environ["WORKBUDDY_ORIGINAL_HTTP_PROXY"] = _orig
    # 按实际存储键删除（Windows 上 os.environ 键大小写会归一化，需遍历真实键名）
    removed = []
    for k in list(os.environ.keys()):
        if k.upper() in proxy_vars:
            del os.environ[k]
            removed.append(k)
    # 兜底：明确声明所有地址直连（个别库会读 no_proxy）
    os.environ["NO_PROXY"] = "*"
    os.environ["no_proxy"] = "*"
    if removed:
        logger.info("已关闭系统代理（强制国内直连），清除变量: " + ", ".join(removed))


def bind_server(port):
    """尝试绑定端口，被占用则自动递增找可用端口。返回 (httpd, actual_port)。"""
    from web.server import create_server
    last_err = None
    for i in range(20):
        p = port + i
        try:
            httpd, _ = create_server(p)
            return httpd, p
        except OSError as e:
            last_err = e
            # Windows WSAEADDRINUSE=10048 / Linux EADDRINUSE=98
            if getattr(e, "errno", None) in (10048, 98, 10013):
                continue
            raise
    raise RuntimeError(f"无法找到可用端口（{port}~{port + 19} 均被占用）: {last_err}")


def _show_error(title, msg):
    """在无控制台（windowed 打包）下用系统弹窗提示错误。"""
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, msg, title, 0x10)  # MB_ICONERROR
    except Exception:
        print(f"[{title}] {msg}")


def _banner():
    print("=" * 56)
    print(f"  {APP_NAME} v{APP_VERSION}")
    print("  本地可视化管理面板")
    print("=" * 56)


def main():
    _banner()
    try:
        cfg = get_config()
    except Exception as e:
        _show_error(APP_NAME, f"配置文件读取失败：\n{e}")
        sys.exit(1)
    port = int(cfg.get("advanced", {}).get("port", 8765))

    # 强制国内直连、不走系统代理（避免 Clash 等把国内 API 路由到失效上游导致解析超时）
    if cfg.get("advanced", {}).get("bypass_system_proxy", True):
        _disable_system_proxy()

    # 单实例检测
    if _probe_self(port):
        print(f"程序已在运行（端口 {port}），正在打开管理面板...")
        open_browser(port)
        return

    # 绑定端口（被占用则自动换）
    try:
        httpd, actual_port = bind_server(port)
    except Exception as e:
        msg = f"本地 Web 服务启动失败：\n{e}\n\n请检查端口是否被占用，或修改「高级设置」中的端口号。"
        _show_error(APP_NAME + " 启动失败", msg)
        print(msg)
        sys.exit(1)

    if actual_port != port:
        print(f"[提示] 端口 {port} 已被占用，本次已改用端口 {actual_port}")
        logger.warning(f"端口 {port} 已被占用，改用 {actual_port}")

    # 启动 Web 服务（后台线程）
    web_thread = threading.Thread(target=httpd.serve_forever, name="web-server", daemon=True)
    web_thread.start()

    url = f"http://127.0.0.1:{actual_port}/"
    logger.info(f"[Web] 管理面板已启动: {url}")
    print(f"\n  管理面板: {url}")
    print(f"  请在浏览器中配置 WeFlow / 抖音 / 微信后，点击「启动监听」。")

    # 自动打开浏览器
    if cfg.get("advanced", {}).get("auto_open_browser", True):
        def _open():
            time.sleep(1.0)
            open_browser(actual_port)
        threading.Thread(target=_open, daemon=True).start()

    # 主线程保持
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        print("\n正在关闭 Web 服务...")
        try:
            httpd.shutdown()
            httpd.server_close()
        except Exception:
            pass
        print("已退出。")


if __name__ == "__main__":
    main()
