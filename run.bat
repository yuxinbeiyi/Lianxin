@echo off
setlocal EnableExtensions
chcp 65001 >nul

rem 中文注释：普通用户启动即可，聊天记录、配置和日志均保存在当前用户目录。
set "PROJECT_ROOT=%~dp0"
cd /d "%PROJECT_ROOT%"
set "PYTHONUTF8=1"

if not exist ".venv\Scripts\python.exe" (
    echo [提示] 首次运行需要先完成环境初始化。
    call "%PROJECT_ROOT%bootstrap.bat"
    if errorlevel 1 exit /b 1
)

call ".venv\Scripts\activate.bat"
python main.py
if errorlevel 1 (
    echo.
    echo [错误] 莲心AI异常退出，详细信息请查看 %USERPROFILE%\.lianxin\logs 或项目 logs 目录。
    pause
)
