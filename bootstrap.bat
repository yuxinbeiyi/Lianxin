@echo off
setlocal EnableExtensions
chcp 65001 >nul

rem 中文注释：此脚本只在当前用户权限下创建虚拟环境和初始化本地配置。
set "PROJECT_ROOT=%~dp0"
cd /d "%PROJECT_ROOT%"

where py >nul 2>nul
if errorlevel 1 (
    echo [错误] 未找到 Python 启动器 py，请先安装 Python 3.11 或更高版本。
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo [1/3] 正在创建虚拟环境...
    py -3.11 -m venv .venv 2>nul
    if errorlevel 1 py -3 -m venv .venv
    if errorlevel 1 (
        echo [错误] 虚拟环境创建失败。
        pause
        exit /b 1
    )
)

call ".venv\Scripts\activate.bat"
echo [2/3] 正在安装依赖...
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
if errorlevel 1 (
    echo [错误] 依赖安装失败，请检查 Python 版本和网络连接。
    pause
    exit /b 1
)

rem 中文注释：API Key 等个人凭据只写入用户目录，绝不写回项目目录。
set "LIANXIN_DATA=%USERPROFILE%\.lianxin"
if not exist "%LIANXIN_DATA%" mkdir "%LIANXIN_DATA%"
if not exist "%LIANXIN_DATA%\user_config.json" (
    copy /y "user_config.json.example" "%LIANXIN_DATA%\user_config.json" >nul
)

echo [3/3] 初始化完成。
echo 请在 %LIANXIN_DATA%\user_config.json 中填写自己的 API Key。
pause
