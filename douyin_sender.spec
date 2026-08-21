# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller 打包配置（onedir 模式）。

用法：.venv\\Scripts\\pyinstaller.exe douyin_sender.spec
产物：dist/抖音视频自动发送/抖音视频自动发送.exe
"""
import os
import glob

from PyInstaller.utils.hooks import collect_all, collect_submodules

datas = []
binaries = []
hiddenimports = []

# 业务依赖的第三方包：递归收集数据文件 / 二进制 / 隐藏导入
for pkg in ("f2", "wxauto4", "uiautomation", "comtypes", "Cryptodome", "certifi", "anyio"):
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception:
        pass

# anyio 后端动态导入
hiddenimports += ["anyio._backends._asyncio", "anyio._backends._trio"]

# 新版 pywin32 用 __import_pywin32_system_module__ 动态加载 pythoncom312.dll 等，
# PyInstaller 静态分析无法追踪，需显式收集 pywin32_system32 下的 DLL。
_sp = os.path.join(os.getcwd(), ".venv", "Lib", "site-packages")
p32_dir = os.path.join(_sp, "pywin32_system32")
if os.path.isdir(p32_dir):
    for _f in glob.glob(os.path.join(p32_dir, "*.dll")):
        binaries.append((_f, "pywin32_system32"))

# pywin32 常见隐藏导入
hiddenimports += ["win32timezone", "win32api", "win32gui", "win32process", "win32con"]

# 静态前端文件
static_src = os.path.join(os.getcwd(), "web", "static")
datas.append((static_src, "web/static"))

a = Analysis(
    ["app.py"],
    pathex=[os.getcwd()],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pytest", "matplotlib"],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="抖音视频自动发送",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,         # 无控制台窗口（最终发布版；调试可改 True）
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="抖音视频自动发送",
)
