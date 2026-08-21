@echo off
cd /d "%~dp0"

if not exist ".venv\Scripts\pyinstaller.exe" (
    echo [错误] 未找到 .venv\Scripts\pyinstaller.exe
    echo 请先安装依赖：uv pip install --python .venv\Scripts\python.exe pyinstaller
    pause
    exit /b 1
)

echo 正在打包（onedir，无控制台）...
".venv\Scripts\pyinstaller.exe" douyin_sender.spec --noconfirm --clean
if errorlevel 1 (
    echo.
    echo [失败] 打包出错，请查看上方日志
    pause
    exit /b 1
)

echo 正在复制配置、工具与数据到 dist...
if not exist "dist\抖音视频自动发送\config" mkdir "dist\抖音视频自动发送\config"
copy /y "config\config.json" "dist\抖音视频自动发送\config\config.json" >nul
xcopy /e /i /y "tools\*" "dist\抖音视频自动发送\tools\" >nul
if not exist "dist\抖音视频自动发送\data" mkdir "dist\抖音视频自动发送\data"
copy /y "data\wxid_displayname_mapping.json" "dist\抖音视频自动发送\data\wxid_displayname_mapping.json" >nul

echo.
echo 打包完成！产物位于 dist\抖音视频自动发送\
pause
