@echo off
chcp 65001 >nul
echo ============================================
echo   莲心AI 打包脚本 - PyInstaller
echo ============================================
echo.

call conda activate lianxin
if errorlevel 1 (
    echo [错误] 无法激活 conda 环境 lianxin
    pause
    exit /b 1
)

if exist dist\LianXinAI rmdir /s /q dist\LianXinAI
if exist build rmdir /s /q build

echo.
echo [1/2] PyInstaller 打包中...
echo.

pyinstaller ^
    --name LianXinAI ^
    --windowed ^
    --onedir ^
    --add-data "assets;assets" ^
    --add-data "vision;vision" ^
    --hidden-import=PyQt5.QtCore ^
    --hidden-import=PyQt5.QtGui ^
    --hidden-import=PyQt5.QtWidgets ^
    --hidden-import=faster_whisper ^
    --hidden-import=funasr ^
    --hidden-import=faiss ^
    --hidden-import=sentence_transformers ^
    --hidden-import=aiohttp ^
    --hidden-import=websockets ^
    --hidden-import=pygame ^
    --hidden-import=onnxruntime ^
    --collect-all funasr ^
    --collect-all faster_whisper ^
    --exclude-module=torch.distributed ^
    --exclude-module=torchvision ^
    --exclude-module=torchaudio ^
    --clean ^
    main.py

if errorlevel 1 (
    echo [错误] 打包失败
    pause
    exit /b 1
)

echo.
echo [2/2] 创建运行时目录...
mkdir dist\LianXinAI\user_data 2>nul
mkdir dist\LianXinAI\memory 2>nul
mkdir dist\LianXinAI\logs 2>nul
copy README.md dist\LianXinAI\README.md >nul 2>&1

echo.
echo ============================================
echo   打包完成！输出: dist\LianXinAI\
echo   压缩整个文件夹为 zip 即可发布
echo ============================================
pause