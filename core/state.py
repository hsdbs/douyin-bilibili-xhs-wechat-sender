# -*- coding: utf-8 -*-
"""
运行时状态管理模块。

跟踪各外部依赖（微信客户端、WeFlow 服务、抖音解析连通性）的健康状态，
并提供自检探测函数。
"""
import os
import threading
import time

from core.logger import logger

_lock = threading.Lock()

# 运行时全局状态字典
_STATE = {
    "wechat_running": False,        # 微信 PC 版进程是否在运行
    "wechat_connected": False,      # wxauto 能否连接微信
    "weflow_connected": False,      # WeFlow API 是否可达
    "douyin_ok": False,             # 抖音解析是否可用（游客态）
    "bilibili_ok": False,           # B站解析依赖（yutto + ffmpeg）是否就绪
    "xhs_ok": False,                # 小红书解析引擎是否就绪
    "listener_running": False,      # 主监听 Worker 是否正在运行
    "listener_start_time": None,    # 监听启动时间戳
    "last_check_time": None,        # 最近一次环境检测时间
}


def get_state():
    """获取运行时状态副本。"""
    with _lock:
        s = dict(_STATE)
    return s


def set_state(**kwargs):
    """更新运行时状态。"""
    with _lock:
        for k, v in kwargs.items():
            if k in _STATE:
                _STATE[k] = v


def set_listener_running(running: bool):
    """设置监听运行状态。"""
    with _lock:
        _STATE["listener_running"] = bool(running)
        _STATE["listener_start_time"] = time.time() if running else None


def check_environment():
    """执行全面的外部依赖与环境自检（耗时约 1~3 秒），并更新全局状态。"""
    logger.info("[自检] 开始执行环境依赖探测...")

    # 1. 微信进程检测
    wx_proc = False
    try:
        import subprocess
        out = subprocess.check_output(
            'tasklist /fi "imagename eq WeChat.exe" /fi "imagename eq Weixin.exe"',
            shell=True,
            text=True,
            errors="ignore"
        )
        wx_proc = ("WeChat.exe" in out) or ("Weixin.exe" in out)
    except Exception as e:
        logger.debug(f"[自检] 微信进程探测异常: {e}")

    # 2. wxauto4 连接检测（只在微信进程存在时尝试，避免无效弹窗/等待）
    wx_conn = False
    if wx_proc:
        try:
            from wxauto4 import WeChat
            w = WeChat()
            wx_conn = True
        except Exception as e:
            logger.debug(f"[自检] wxauto 连接失败: {e}")

    # 3. WeFlow 连通性测试
    wf_conn = False
    try:
        from main import test_weflow_connection
        wf_conn, _ = test_weflow_connection()
    except Exception as e:
        logger.debug(f"[自检] WeFlow 探测异常: {e}")

    # 4. 抖音连通性测试（内置游客态）
    dy_ok = False
    try:
        from douyin_parser import test_douyin
        dy_ok, _ = test_douyin()
    except Exception as e:
        logger.debug(f"[自检] 抖音游客态探测异常: {e}")

    # 5. B站连通性测试（yutto + ffmpeg）
    bl_ok = False
    try:
        from bilibili_parser import test_bilibili
        bl_ok, _ = test_bilibili()
    except Exception as e:
        logger.debug(f"[自检] B站依赖探测异常: {e}")

    # 6. 小红书连通性测试（内置 tools/xhs 引擎）
    xh_ok = False
    try:
        from xhs_parser import test_xhs
        xh_ok, _ = test_xhs()
    except Exception as e:
        logger.debug(f"[自检] 小红书引擎探测异常: {e}")

    with _lock:
        _STATE["wechat_running"] = wx_proc
        _STATE["wechat_connected"] = wx_conn
        _STATE["weflow_connected"] = wf_conn
        _STATE["douyin_ok"] = dy_ok
        _STATE["bilibili_ok"] = bl_ok
        _STATE["xhs_ok"] = xh_ok
        _STATE["last_check_time"] = time.strftime("%Y-%m-%d %H:%M:%S")

    logger.info(
        f"[自检] 完成: 微信进程={wx_proc}, wxauto={wx_conn}, WeFlow={wf_conn}, "
        f"抖音={dy_ok}, B站={bl_ok}, 小红书={xh_ok}"
    )
    return get_state()
