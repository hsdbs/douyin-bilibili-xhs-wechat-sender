# -*- coding: utf-8 -*-
"""
Web 管理面板统一入口程序。

功能：
  1. 初始化统一配置（core.config）与运行时状态（core.state）
  2. 启动 Web 服务（web.server），提供 Dashboard/配置/任务/日志/控制等 API
  3. 自动在默认浏览器中打开管理面板页面（http://127.0.0.1:8765）
  4. 保持主进程运行并响应 Ctrl+C 优雅退出

打包为 EXE 时：
  - PyInstaller onedir 模式直接执行此入口
  - 启动后托盘/控制台常驻，后台异步响应
"""
import os
import signal
import sys
import threading
import time
import webbrowser

# 确保项目根目录在 sys.path 中
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from core.config import get_config, load_config
from core.logger import logger
from core import state
from web.server import start_server, stop_server


def open_browser_delayed(url, delay=1.2):
    """延迟打开浏览器，等待 Web 服务完全启动。"""
    def _open():
        time.sleep(delay)
        try:
            webbrowser.open(url, new=2)
        except Exception as e:
            logger.warning(f"[系统] 自动打开浏览器失败: {e}，请手动访问 {url}")
    t = threading.Thread(target=_open, daemon=True, name="BrowserOpener")
    t.start()


def main():
    logger.info("=" * 60)
    logger.info("抖音视频自动发送 · 可视化管理面板 启动中...")
    logger.info("=" * 60)

    # 1. 加载配置（首次运行会自动创建默认 config/config.json 并迁移旧数据）
    try:
        cfg = load_config()
        adv = cfg.get("advanced", {})
        port = int(adv.get("port", 8765))
        auto_open = bool(adv.get("auto_open_browser", True))
    except Exception as e:
        logger.error(f"[系统] 加载配置失败: {e}")
        port = 8765
        auto_open = True

    # 2. 启动 Web 服务
    server = start_server(port=port)
    if not server:
        logger.error(f"[系统] Web 服务未能启动（端口 {port} 可能被占用），程序退出")
        sys.exit(1)

    url = f"http://127.0.0.1:{port}"
    logger.info(f"[系统] Web 管理面板已就绪: {url}")

    # 3. 异步探测环境依赖（微信/WeFlow/抖音游客态）
    threading.Thread(
        target=state.check_environment,
        daemon=True,
        name="InitEnvCheck"
    ).start()

    # 4. 自动打开浏览器
    if auto_open:
        open_browser_delayed(url)

    # 5. 注册退出信号处理
    stop_event = threading.Event()

    def _sig_handler(sig, frame):
        logger.info(f"[系统] 收到退出信号 ({sig})，正在关闭...")
        stop_event.set()

    try:
        signal.signal(signal.SIGINT, _sig_handler)
        signal.signal(signal.SIGTERM, _sig_handler)
    except (ValueError, AttributeError):
        pass  # Windows 部分环境可能不支持某些信号

    logger.info("[系统] 服务运行中，按 Ctrl+C 可停止程序")
    logger.info("-" * 60)

    # 6. 主线程休眠等待退出
    try:
        while not stop_event.is_set():
            time.sleep(0.5)
    except KeyboardInterrupt:
        logger.info("[系统] 用户中断 (KeyboardInterrupt)")
    finally:
        logger.info("[系统] 正在清理并停止所有服务...")
        stop_server()
        logger.info("[系统] 程序已退出")


if __name__ == "__main__":
    main()
